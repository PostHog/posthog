// The host only delivers the MessagePort after the artifact iframe's load
// event, which fires after the app's module scripts have already run, so any
// ph.* call issued during mount lands before the port exists. Those messages
// queue (bounded, in case the host never connects) and flush on connect.
;(() => {
    const channel = 'posthog-canvas',
        pending = new Map(),
        queued = []
    let sequence = 0,
        port
    const post = (message) => {
        const payload = { channel, ...message }
        if (port) {
            port.postMessage(payload)
        } else if (queued.length < 256) {
            queued.push(payload)
        }
    }
    const call = (method, payload) =>
        new Promise((resolve, reject) => {
            if (!port && (method === 'actionInvoke' || method === 'agentRequest')) {
                reject(new Error('Canvas actions require a user action'))
                return
            }
            const id = String(++sequence)
            const timer = setTimeout(() => {
                pending.delete(id)
                const queuedIndex = queued.findIndex((message) => message.type === 'data-request' && message.id === id)
                if (queuedIndex > -1) queued.splice(queuedIndex, 1)
                reject(new Error('Canvas request timed out'))
            }, 30000)
            pending.set(id, { resolve, reject, timer })
            post({ type: 'data-request', id, method, payload })
        })
    const applyTheme = (theme) => {
        if (theme !== 'dark' && theme !== 'light') return
        const dark = theme === 'dark'
        document.documentElement.classList.toggle('dark', dark)
        document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
    }
    const fragmentParams = new URLSearchParams(location.hash.slice(1))
    applyTheme(fragmentParams.get('theme'))
    let config = {}
    try {
        const rawConfig = fragmentParams.get('config')
        if (rawConfig) config = Object.freeze(JSON.parse(rawConfig))
    } catch {
        config = {}
    }
    const receive = (event) => {
        if (event.data?.channel !== channel) return
        if (event.data.type === 'set-theme') {
            applyTheme(event.data.theme)
            return
        }
        if (event.data.type !== 'data-response') return
        const request = pending.get(event.data.id)
        if (!request) return
        pending.delete(event.data.id)
        clearTimeout(request.timer)
        event.data.ok
            ? request.resolve(event.data.result)
            : request.reject(new Error(event.data.error ?? 'Canvas request failed'))
    }
    const capture = (event, properties, distinctId) => {
        const normalized = properties ?? {}
        let serialized
        try {
            serialized = JSON.stringify(normalized)
        } catch {
            throw new Error('Canvas capture properties must be serializable')
        }
        if (typeof serialized !== 'string' || serialized.length > 16384)
            throw new Error('Canvas capture properties are too large')
        return call('capture', { event, properties: normalized, distinctId })
    }
    const openExternal = (value) => {
        const url = new URL(value)
        const github =
            url.hostname === 'github.com' &&
            !url.username &&
            !url.password &&
            !url.port &&
            !url.search &&
            new RegExp('^/[a-z0-9-]+/[a-z0-9_.-]+/pull/[1-9][0-9]*(/(files|commits|checks))?/?$', 'i').test(
                url.pathname
            )
        if (
            url.protocol !== 'https:' ||
            !(url.hostname === 'posthog.com' || url.hostname.endsWith('.posthog.com') || github)
        )
            throw new Error('Canvas external URL is not allowed')
        post({ type: 'open-external', url: url.href })
    }
    window.ph = {
        config,
        loadInsight: (shortId, options) =>
            call('loadInsight', {
                shortId,
                dateRange: options?.dateRange,
                variables: options?.variables,
                refresh: options?.refresh,
            }),
        query: (query, params, options) =>
            call(
                'query',
                typeof query === 'string'
                    ? { hogql: query, params: params ?? {}, refresh: options?.refresh }
                    : { query, params: params ?? {}, refresh: options?.refresh }
            ),
        capture,
        openExternal,
        navigate: {
            toTask: (taskId) => post({ type: 'navigate', nav: { target: 'task', taskId } }),
            toNewTask: (options) => {
                if (!navigator.userActivation?.isActive) throw new Error('Opening a task requires a user action')
                post({
                    type: 'navigate',
                    nav: {
                        target: options ? 'compose-task' : 'new-task',
                        prompt: options?.prompt,
                        repository: options?.repository,
                    },
                })
            },
            toCanvas: (dashboardId) => post({ type: 'navigate', nav: { target: 'canvas', dashboardId } }),
            toNewCanvas: () => post({ type: 'navigate', nav: { target: 'new-canvas' } }),
        },
        agent: { request: (prompt) => call('agentRequest', { prompt }) },
        state: {
            get: (key, opts) => call('stateGet', { key, scope: opts?.scope || 'user' }),
            set: (key, value, opts) =>
                call('stateSet', { key, value: value === undefined ? null : value, scope: opts?.scope || 'user' }),
            list: (opts) => call('stateList', { scope: opts?.scope }),
        },
        actions: { invoke: (verb, payload) => call('actionInvoke', { verb, payload: payload ?? {} }) },
        connectors: {
            call: (provider, tool, args, options) =>
                call('connectorCall', { provider, tool, arguments: args ?? {}, refresh: options?.refresh }),
            connect: (provider) => {
                if (!navigator.userActivation?.isActive) throw new Error('Connecting a provider requires a user action')
                post({ type: 'navigate', nav: { target: 'connect', provider } })
            },
        },
    }
    addEventListener('message', (event) => {
        if (
            port ||
            event.source !== parent ||
            event.data?.channel !== channel ||
            event.data?.type !== 'connect' ||
            !event.ports[0]
        )
            return
        port = event.ports[0]
        port.addEventListener('message', receive)
        port.start()
        while (queued.length) port.postMessage(queued.shift())
        if (document.readyState !== 'loading') post({ type: 'ready' })
        if (document.readyState === 'complete') post({ type: 'rendered' })
    })
    addEventListener('error', (event) =>
        post({ type: 'error', message: event.message || 'Canvas runtime error', stack: event.error?.stack })
    )
    addEventListener('unhandledrejection', (event) =>
        post({
            type: 'error',
            message: event.reason instanceof Error ? event.reason.message : String(event.reason),
            stack: event.reason instanceof Error ? event.reason.stack : undefined,
        })
    )
    const cspSeen = new Set()
    addEventListener('securitypolicyviolation', (event) => {
        const directive = event.effectiveDirective || 'unknown'
        if (cspSeen.has(directive)) return
        cspSeen.add(directive)
        post({ type: 'error', message: 'SecurityPolicyViolationError: ' + directive })
    })
    addEventListener('DOMContentLoaded', () => post({ type: 'ready' }))
    addEventListener('load', () => post({ type: 'rendered' }))
})()
