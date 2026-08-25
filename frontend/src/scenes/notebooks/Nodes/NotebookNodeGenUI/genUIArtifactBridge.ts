import type { GenUIFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

const CANVAS_CHANNEL = 'posthog-canvas'
export const NOTEBOOK_FRAME_KEY_PREFIX = '__posthog_notebook_frame__:'
const MAX_CONCURRENT_REQUESTS = 8
const MAX_REQUEST_BYTES = 8 * 1024
const REQUEST_TIMEOUT_MS = 30_000

type ArtifactMessage = {
    channel?: unknown
    type?: unknown
    id?: unknown
    method?: unknown
    payload?: unknown
    message?: unknown
}

export async function readGenUIFrame(
    allowedFrames: string[],
    loadFrame: (name: string) => Promise<GenUIFrameApi>,
    payload: unknown
): Promise<GenUIFrameApi> {
    const key =
        typeof payload === 'object' && payload !== null && typeof (payload as { key?: unknown }).key === 'string'
            ? (payload as { key: string }).key
            : ''
    const name = key.startsWith(NOTEBOOK_FRAME_KEY_PREFIX) ? key.slice(NOTEBOOK_FRAME_KEY_PREFIX.length) : ''
    if (!name || !allowedFrames.includes(name)) {
        throw new Error('This dataframe is not available to the visualization')
    }
    return await loadFrame(name)
}

export type GenUIHostCallbacks = {
    onDataRequest: (method: string, payload: unknown) => Promise<unknown> | unknown
    onError?: () => void
    onRendered?: () => void
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
        if (message.type === 'error') {
            callbacks().onError?.()
            return
        }
        if (message.type === 'rendered') {
            callbacks().onRendered?.()
            return
        }
        if (message.type !== 'data-request' || typeof message.id !== 'string' || typeof message.method !== 'string') {
            return
        }
        if (message.method !== 'stateGet') {
            post({
                channel: CANVAS_CHANNEL,
                type: 'data-response',
                id: message.id,
                ok: false,
                error: 'This Canvas method is not available in notebook visualizations',
            })
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
        const request = Promise.resolve().then(() => callbacks().onDataRequest('stateGet', message.payload))
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
                error: error instanceof Error ? error.message : 'Visualization data request failed',
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
