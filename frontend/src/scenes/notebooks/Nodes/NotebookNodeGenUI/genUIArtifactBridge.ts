import type { GenUIFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

export type GenUITheme = 'light' | 'dark'

const CANVAS_CHANNEL = 'posthog-canvas'
const MAX_CONCURRENT_REQUESTS = 8
const MAX_REQUEST_BYTES = 8 * 1024
const REQUEST_TIMEOUT_MS = 30_000

export type GenUICapabilities = {
    notebook: {
        frames: string[]
    }
}

export function parseGenUICapabilities(raw: unknown): GenUICapabilities | undefined {
    if (typeof raw !== 'object' || raw === null) {
        return undefined
    }
    const notebook = (raw as Record<string, unknown>).notebook
    if (typeof notebook !== 'object' || notebook === null) {
        return undefined
    }
    const frames = (notebook as Record<string, unknown>).frames
    return {
        notebook: {
            frames: Array.isArray(frames) ? frames.filter((name): name is string => typeof name === 'string') : [],
        },
    }
}

export async function readGenUIFrame(
    capabilities: GenUICapabilities | undefined,
    loadFrame: (name: string) => Promise<GenUIFrameApi>,
    payload: unknown
): Promise<GenUIFrameApi> {
    const name =
        typeof payload === 'object' && payload !== null && typeof (payload as { name?: unknown }).name === 'string'
            ? (payload as { name: string }).name
            : ''
    if (!name) {
        throw new Error('ph.readFrame(name) requires a dataframe name')
    }
    if (!capabilities?.notebook.frames.includes(name)) {
        throw new Error(`Dataframe "${name}" is not allowed by this visualization`)
    }
    return await loadFrame(name)
}

export function buildGenUIArtifactHostDocument(artifactUrl: string, theme: GenUITheme): string {
    const artifactOrigin = new URL(artifactUrl).origin
    const themedUrl = new URL(artifactUrl)
    themedUrl.hash = `theme=${theme}`
    const serializedArtifactUrl = JSON.stringify(themedUrl.href).replaceAll('<', '\\u003c')

    return `<!doctype html>
<html>
<head>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src ${artifactOrigin}">
<style>html,body,iframe{border:0;height:100%;margin:0;padding:0;width:100%}</style>
</head>
<body>
<script>
const artifactFrame = document.createElement("iframe");
artifactFrame.title = "Generated visualization";
artifactFrame.sandbox = "allow-scripts";
artifactFrame.referrerPolicy = "no-referrer";
artifactFrame.src = ${serializedArtifactUrl};
let artifactLoaded = false;
let bridgePort;
const connect = () => {
  if (!artifactLoaded || !bridgePort) return;
  artifactFrame.contentWindow.postMessage(
    { channel: "${CANVAS_CHANNEL}", type: "connect" },
    "*",
    [bridgePort],
  );
  bridgePort = undefined;
};
artifactFrame.addEventListener("load", () => {
  if (artifactLoaded) return;
  artifactLoaded = true;
  connect();
});
window.addEventListener("message", (event) => {
  if (
    event.source !== parent ||
    event.data?.channel !== "${CANVAS_CHANNEL}-host" ||
    event.data?.type !== "connect" ||
    !event.ports[0]
  ) return;
  bridgePort = event.ports[0];
  connect();
});
document.body.append(artifactFrame);
</script>
</body>
</html>`
}

export type GenUIHostCallbacks = {
    onDataRequest: (method: string, payload: unknown) => Promise<unknown> | unknown
    onError?: (message: string) => void
    onRendered?: () => void
}

type ArtifactMessage = {
    channel?: unknown
    type?: unknown
    id?: unknown
    method?: unknown
    payload?: unknown
    message?: unknown
}

export function createGenUIHostMessageRouter(
    post: (message: Record<string, unknown>) => void,
    callbacks: () => GenUIHostCallbacks
): (message: unknown) => Promise<void> {
    let activeRequests = 0

    return async (raw: unknown): Promise<void> => {
        if (typeof raw !== 'object' || raw === null) {
            return
        }
        const message = raw as ArtifactMessage
        if (message.channel !== CANVAS_CHANNEL) {
            return
        }
        if (message.type === 'error' && typeof message.message === 'string') {
            callbacks().onError?.(message.message)
            return
        }
        if (message.type === 'rendered') {
            callbacks().onRendered?.()
            return
        }
        if (message.type !== 'data-request' || typeof message.id !== 'string' || typeof message.method !== 'string') {
            return
        }

        let requestBytes = Number.POSITIVE_INFINITY
        try {
            requestBytes = JSON.stringify(message.payload).length
        } catch {
            requestBytes = Number.POSITIVE_INFINITY
        }
        if (activeRequests >= MAX_CONCURRENT_REQUESTS || requestBytes > MAX_REQUEST_BYTES) {
            post({
                channel: CANVAS_CHANNEL,
                type: 'data-response',
                id: message.id,
                ok: false,
                error: 'Visualization data request exceeds runtime limits',
            })
            return
        }

        activeRequests += 1
        let timeoutId: ReturnType<typeof setTimeout> | undefined
        const request = Promise.resolve().then(() =>
            callbacks().onDataRequest(message.method as string, message.payload)
        )
        try {
            const result = await Promise.race([
                request,
                new Promise<never>((_, reject) => {
                    timeoutId = setTimeout(
                        () => reject(new Error('Visualization data request timed out')),
                        REQUEST_TIMEOUT_MS
                    )
                }),
            ])
            post({ channel: CANVAS_CHANNEL, type: 'data-response', id: message.id, ok: true, result })
        } catch (error) {
            post({
                channel: CANVAS_CHANNEL,
                type: 'data-response',
                id: message.id,
                ok: false,
                error: error instanceof Error ? error.message : String(error),
            })
        } finally {
            if (timeoutId !== undefined) {
                clearTimeout(timeoutId)
            }
            void request.catch(() => undefined)
            activeRequests -= 1
        }
    }
}
