// The web-app side of the canvas artifact postMessage protocol. A published
// canvas build runs untrusted code in a null-origin sandboxed iframe, so every
// interaction is a structured-clone message and the user's session never
// crosses the boundary: the iframe sends a data-request, the host runs the
// authenticated call and returns only the result. Keep this protocol in sync
// with the desktop host (products/desktop/packages/core/src/canvas/freeformSchemas.ts).

export type CanvasTheme = 'light' | 'dark'

const CANVAS_CHANNEL = 'posthog-canvas'

// Runtime guards on the canvas→host data bridge: canvas code is untrusted, so
// a runaway loop must not pile up unbounded concurrent requests, ship
// oversized payloads, or hold a request slot forever.
const MAX_CONCURRENT_DATA_REQUESTS = 8
const MAX_DATA_REQUEST_BYTES = 64 * 1024
const DATA_REQUEST_TIMEOUT_MS = 30_000

/** The PostHog capabilities frozen into a build's manifest. Requests outside
 * the manifest are refused, matching the desktop host. */
export interface CanvasCapabilities {
    posthog: {
        inlineQueries: boolean
        insights: string[]
        captureEvents: string[]
    }
}

export function parseCanvasCapabilities(raw: unknown): CanvasCapabilities | undefined {
    if (typeof raw !== 'object' || raw === null) {
        return undefined
    }
    const posthogRaw = (raw as Record<string, unknown>).posthog
    if (typeof posthogRaw !== 'object' || posthogRaw === null) {
        return undefined
    }
    const posthog = posthogRaw as Record<string, unknown>
    return {
        posthog: {
            inlineQueries: posthog.inlineQueries === true,
            insights: Array.isArray(posthog.insights) ? posthog.insights.filter((i) => typeof i === 'string') : [],
            captureEvents: Array.isArray(posthog.captureEvents)
                ? posthog.captureEvents.filter((e) => typeof e === 'string')
                : [],
        },
    }
}

export function assertCanvasCapability(
    capabilities: CanvasCapabilities | undefined,
    method: string,
    payload: unknown
): void {
    if (!capabilities) {
        throw new Error('Canvas capability manifest is unavailable')
    }
    const payloadRecord = (typeof payload === 'object' && payload !== null ? payload : {}) as Record<string, unknown>
    switch (method) {
        case 'query':
            if (!capabilities.posthog.inlineQueries) {
                throw new Error('Inline queries are not allowed by this canvas')
            }
            return
        case 'loadInsight':
            if (!capabilities.posthog.insights.includes(payloadRecord.shortId as string)) {
                throw new Error('Insight is not allowed by this canvas')
            }
            return
        case 'capture':
            if (!capabilities.posthog.captureEvents.includes(payloadRecord.event as string)) {
                throw new Error('Event capture is not allowed by this canvas')
            }
            return
        default:
            throw new Error(`Method "${method}" is not allowed by this canvas`)
    }
}

/**
 * The srcDoc host document that nests the artifact iframe. The extra document
 * hop pins a CSP on the artifact (only its own origin may be framed) and owns
 * the MessagePort handshake: the outer app posts a `connect` frame with a
 * port, and the host document forwards it into the artifact once both sides
 * are ready.
 */
export function buildCanvasArtifactHostDocument(artifactUrl: string, theme: CanvasTheme): string {
    const artifactOrigin = new URL(artifactUrl).origin
    // The theme rides the fragment so the artifact runtime (a synchronous head
    // script) applies `.dark` before first paint - the bridge port only
    // connects at the load event, far too late to prevent a light flash.
    // Fragments don't reach the server, so signed artifact URLs stay valid.
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
artifactFrame.title = "Canvas artifact";
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

export interface CanvasHostCallbacks {
    onDataRequest: (method: string, payload: unknown) => Promise<unknown>
    onError?: (message: string) => void
    onRendered?: () => void
}

interface CanvasToHostMessage {
    channel?: unknown
    type?: unknown
    id?: unknown
    method?: unknown
    payload?: unknown
    message?: unknown
}

/**
 * Routes messages arriving from the artifact over the bridge port. Only the
 * data/error/rendered avenues are supported in notebooks: `navigate` and
 * `open-external` are desktop-app affordances and are ignored here.
 */
export function createCanvasHostMessageRouter(
    post: (message: Record<string, unknown>) => void,
    callbacks: () => CanvasHostCallbacks
): (message: unknown) => Promise<void> {
    let activeDataRequests = 0

    const isBoundedPayload = (payload: unknown): boolean => {
        try {
            return JSON.stringify(payload).length <= MAX_DATA_REQUEST_BYTES
        } catch {
            return false
        }
    }

    return async (raw: unknown) => {
        if (typeof raw !== 'object' || raw === null) {
            return
        }
        const message = raw as CanvasToHostMessage
        if (message.channel !== CANVAS_CHANNEL) {
            return
        }
        switch (message.type) {
            case 'data-request': {
                if (typeof message.id !== 'string' || typeof message.method !== 'string') {
                    return
                }
                if (activeDataRequests >= MAX_CONCURRENT_DATA_REQUESTS || !isBoundedPayload(message.payload)) {
                    post({
                        channel: CANVAS_CHANNEL,
                        type: 'data-response',
                        id: message.id,
                        ok: false,
                        error: 'Canvas data request exceeds runtime limits',
                    })
                    return
                }
                activeDataRequests += 1
                try {
                    const result = await Promise.race([
                        callbacks().onDataRequest(message.method, message.payload),
                        new Promise<never>((_, reject) =>
                            setTimeout(
                                () => reject(new Error('Canvas data request timed out')),
                                DATA_REQUEST_TIMEOUT_MS
                            )
                        ),
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
                    activeDataRequests -= 1
                }
                return
            }
            case 'error':
                if (typeof message.message === 'string') {
                    callbacks().onError?.(message.message)
                }
                return
            case 'rendered':
                callbacks().onRendered?.()
                return
        }
    }
}
