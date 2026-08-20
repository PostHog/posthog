import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { UNACTIONABLE_NETWORK_ERROR_MESSAGES } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { setReadOnlyGetter, setReadOnlyNotifier } from 'lib/readOnlyGuard'

import type { FeatureFlagsSet } from '../../../lib/logic/featureFlagLogic'

export const ESCALATION_OPTIONS = [
    { seconds: 30, label: 'Allow for 30s' },
    { seconds: 300, label: 'Allow for 5 min' },
] as const

// Filters `$exception` events whose chain contains a ReadOnlyModeError so the
// read-only feature doesn't spam error tracking for blocks-by-design. The
// chain walk catches wrapped errors (e.g. `new Error('...', { cause: e })`).
// Exported for unit testing.
export function dropReadOnlyExceptions<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string }>
    if (list.some((ex) => ex?.type === 'ReadOnlyModeError')) {
        return null
    }
    return event
}

// Detail messages the backend sends with the three handled auth-gate 403s. The frontend already
// recovers from each of them in `apiStatusLogic` (it opens the 2FA setup modal, shows the
// re-verification toast, or prompts a re-auth), so a rejected request is expected control flow,
// not a bug. posthog-js's error conversion keeps only the error type, message, and stack in
// `$exception_list` — the DRF `code` never reaches `before_send` — so we match on the message,
// which `ApiError` sets from the response `detail`.
//
//   two_factor_setup_required        — posthog/helpers/two_factor_session.py
//   two_factor_verification_required — posthog/helpers/two_factor_session.py
//   sensitive_action_required_reauth — posthog/permissions.py (TimeSensitiveActionPermission)
const HANDLED_AUTH_GATE_MESSAGES = new Set([
    '2FA setup required',
    '2FA verification required',
    'This action requires you to be recently authenticated.',
])

// Filters `$exception` events that are really a handled auth gate, not a crash. When an org
// enforces 2FA, or an action needs recent re-authentication, the API returns a 403 that
// `apiStatusLogic` turns into the setup/verify flow. The many call sites that also
// `captureException` the rejection — kea loaders via `initKea`, and direct captures like
// `reverseProxyCheckerLogic` — would each file it as a fresh error tracking issue, so drop
// them centrally here. Exported for unit testing.
export function dropHandledAuthGateExceptions<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ value?: string }>
    if (list.some((ex) => ex?.value != null && HANDLED_AUTH_GATE_MESSAGES.has(ex.value))) {
        return null
    }
    return event
}

// Filters `$exception` events for requests the browser never sent because the client was offline or
// the document was being torn down. Neither is a defect, and both arrive as unhandled rejections
// from whichever logic happened to be fetching, so each one fingerprints against a different stack
// and files its own error tracking issue. `NetworkError` with reason `network` is deliberately kept:
// a request that failed while the user was online and staying put is worth seeing. Exported for
// unit testing.
export function dropUnactionableNetworkExceptions<
    T extends { event?: string; properties?: Record<string, any> } | null,
>(event: T): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string; value?: string }>
    if (
        list.some(
            (ex) =>
                ex?.type === 'NetworkError' && ex?.value != null && UNACTIONABLE_NETWORK_ERROR_MESSAGES.has(ex.value)
        )
    ) {
        return null
    }
    return event
}

// Browser engines word an unknown-identifier ReferenceError in one of two ways: WebKit says
// "Can't find variable: X", V8 and SpiderMonkey say "X is not defined". Both name a single
// identifier. Our own bundle never leaves such an identifier undefined at runtime.
const UNKNOWN_IDENTIFIER_REFERENCE_ERROR = /^(Can't find variable: \S+|\S+ is not defined)$/

// Filters `$exception` events that a browser extension or an in-app browser injected into the page.
// Each one is an unhandled ReferenceError for an identifier our code never defines (for example
// `WeixinJSBridge`, `__firefox__`, or `Can't find variable: pos`), and posthog-js captures it
// through the global handler with no stack frames because the throwing script is not ours. A real
// ReferenceError in our own bundle carries a stack, so the empty-stack check keeps those. Each
// injected variant fingerprints to its own error tracking issue, so drop the whole class here.
// Exported for unit testing.
export function dropInjectedScriptReferenceErrors<
    T extends { event?: string; properties?: Record<string, any> } | null,
>(event: T): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{
        type?: string
        value?: string
        mechanism?: { handled?: boolean }
        stacktrace?: { frames?: unknown[] }
    }>
    const hasFrames = list.some((ex) => (ex?.stacktrace?.frames?.length ?? 0) > 0)
    const isUnhandled = list.every((ex) => ex?.mechanism?.handled === false)
    const isUnknownIdentifierReferenceError = list.some(
        (ex) => ex?.type === 'ReferenceError' && ex?.value != null && UNKNOWN_IDENTIFIER_REFERENCE_ERROR.test(ex.value)
    )
    if (!hasFrames && isUnhandled && isUnknownIdentifierReferenceError) {
        return null
    }
    return event
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface selfReadOnlyModeLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    escalatedUntil: number | null
    isEscalated: boolean
    isFlagEnabled: boolean
    isReadOnly: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface selfReadOnlyModeLogicActions {
    endEscalation: () => {
        value: true
    }
    escalate: (durationSeconds: number) => {
        durationSeconds: number
    }
    notifyBlocked: (method: string) => {
        method: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface selfReadOnlyModeLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        isFlagEnabled: (featureFlags: FeatureFlagsSet) => boolean
        isEscalated: (escalatedUntil: number | null) => boolean
        isReadOnly: (isFlagEnabled: boolean, isEscalated: boolean) => boolean
    }
}

export type selfReadOnlyModeLogicType = MakeLogicType<
    selfReadOnlyModeLogicValues,
    selfReadOnlyModeLogicActions,
    Record<string, any>,
    selfReadOnlyModeLogicMeta
>

export const selfReadOnlyModeLogic = kea<selfReadOnlyModeLogicType>([
    path(['layout', 'navigation', 'SelfReadOnlyNotice', 'selfReadOnlyModeLogic']),

    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        escalate: (durationSeconds: number) => ({ durationSeconds }),
        endEscalation: true,
        notifyBlocked: (method: string) => ({ method }),
    }),

    reducers({
        escalatedUntil: [
            null as number | null,
            {
                escalate: (_, { durationSeconds }) => Date.now() + durationSeconds * 1000,
                endEscalation: () => null,
            },
        ],
    }),

    selectors({
        isFlagEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: import('lib/logic/featureFlagLogic').FeatureFlagsSet): boolean =>
                !!featureFlags[FEATURE_FLAGS.READ_ONLY_MODE],
        ],
        // isEscalated reads Date.now() inside a selector — selectors aren't time-reactive.
        // It only flips back to false when escalatedUntil is reset by the setTimeout in the
        // `escalate` listener firing `endEscalation`. Acceptable: the timer runs even on
        // hidden tabs (pauseOnPageHidden: false).
        isEscalated: [
            (s) => [s.escalatedUntil],
            (until: number | null): boolean => until !== null && until > Date.now(),
        ],
        isReadOnly: [
            (s) => [s.isFlagEnabled, s.isEscalated],
            (isFlagEnabled: boolean, isEscalated: boolean): boolean => isFlagEnabled && !isEscalated,
        ],
    }),

    listeners(({ actions, cache }) => ({
        escalate: ({ durationSeconds }) => {
            cache.disposables.add(
                () => {
                    const id = setTimeout(() => actions.endEscalation(), durationSeconds * 1000)
                    return () => clearTimeout(id)
                },
                'escalationTimer',
                { pauseOnPageHidden: false }
            )
            posthog.capture?.('read_only_escalated', { duration_seconds: durationSeconds })
        },
        endEscalation: () => {
            cache.disposables.dispose('escalationTimer')
            lemonToast.info('Back to read-only mode.', { toastId: 'read-only-resumed' })
            posthog.capture?.('read_only_ended')
        },
        // Analytics-only — the user-visible toast is no longer fired here. Catch blocks
        // that match `e instanceof ApiError` already surface `ReadOnlyModeError.detail`.
        notifyBlocked: ({ method }) => {
            posthog.capture?.('read_only_write_blocked', { method })
        },
    })),

    afterMount(({ actions }) => {
        // Read via `findMounted()` rather than capturing the `values` proxy:
        // the store path can be torn down (HMR, logout, kea resetContext) without
        // our `beforeUnmount` clearing the getter, which would throw a kea
        // "path not in store" error on the next mutation.
        setReadOnlyGetter(() => selfReadOnlyModeLogic.findMounted()?.values.isReadOnly ?? false)
        setReadOnlyNotifier((method) => actions.notifyBlocked(method))

        // Central error-tracking filter chain — drops `$exception` events for a ReadOnlyModeError
        // (a block by design), for the handled auth gates (2FA setup/verify, re-auth), for the
        // network failures that only describe the client's situation, and for the ReferenceErrors
        // that browser extensions and in-app browsers inject. Catches direct captures *and* wrapped
        // errors (`new Error('...', { cause: readOnlyErr })`). This logic mounts in the authenticated
        // app, where every gated request happens, and no other code that runs there sets
        // `before_send`, so we own this config slot.
        posthog.set_config({
            before_send: [
                dropReadOnlyExceptions,
                dropHandledAuthGateExceptions,
                dropUnactionableNetworkExceptions,
                dropInjectedScriptReferenceErrors,
            ],
        })

        // The user-facing toast for blocked writes is shown by the standard
        // `e instanceof ApiError → lemonToast.error(e.detail)` pattern that
        // every write call-site already implements. ReadOnlyModeError extends
        // ApiError and carries a method-specific `detail`, so no extra hook
        // is needed.
    }),

    beforeUnmount(() => {
        setReadOnlyGetter(null)
        setReadOnlyNotifier(null)
        // Releasing ownership of `before_send` — this clears the whole filter chain set on mount.
        posthog.set_config({ before_send: undefined })
    }),
])
