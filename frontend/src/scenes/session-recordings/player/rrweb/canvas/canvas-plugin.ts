import posthog from 'posthog-js'

import { Replayer, canvasMutation } from '@posthog/rrweb'
import { ReplayPlugin } from '@posthog/rrweb'
import {
    CanvasArg,
    EventType,
    IncrementalSource,
    canvasMutationData,
    canvasMutationParam,
    eventWithTime,
} from '@posthog/rrweb-types'

import { debounce } from 'lib/utils'

import { deserializeCanvasArg } from './deserialize-canvas-args'

type CanvasEventWithTime = eventWithTime & {
    type: EventType.IncrementalSnapshot
    data: canvasMutationData
}

function isCanvasMutation(e: eventWithTime): e is CanvasEventWithTime {
    return e.type === EventType.IncrementalSnapshot && e.data.source === IncrementalSource.CanvasMutation
}

function quickFindClosestCanvasEventIndex(
    events: CanvasEventWithTime[] | undefined,
    target: CanvasEventWithTime | undefined,
    start: number,
    end: number
): number {
    if (!target || !events || !events.length) {
        return -1
    }

    if (start > end) {
        return end
    }

    if (start < 0 || end > events.length - 1) {
        return -1
    }

    const mid = Math.floor((start + end) / 2)

    // in production, we do sometimes see this be undefined
    const middleEvent = events[mid]
    if (!middleEvent) {
        return -1
    }

    return target.timestamp <= middleEvent.timestamp
        ? quickFindClosestCanvasEventIndex(events, target, start, mid - 1)
        : quickFindClosestCanvasEventIndex(events, target, mid + 1, end)
}

const PRELOAD_BUFFER_SIZE = 20
const BUFFER_TIME = 30000 // 30 seconds
const DEBOUNCE_MILLIS = 250 // currently using 4fps for all recordings

export const CanvasReplayerPlugin = (events: eventWithTime[]): ReplayPlugin => {
    const canvases = new Map<number, HTMLCanvasElement>([])
    const containers = new Map<number, HTMLImageElement>([])
    const imageMap = new Map<eventWithTime | string, HTMLImageElement>()
    const canvasEventMap = new Map<eventWithTime | string, canvasMutationParam>()
    const pruneQueue: eventWithTime[] = []
    let nextPreloadIndex: number | null = null

    const canvasMutationEvents = events.filter(isCanvasMutation)

    // Buffers mutations from user interactions before Replayer was ready
    const handleQueue = new Map<number, [CanvasEventWithTime, Replayer]>()

    // only processes a single mutation event in cases when the user is scrubbing
    // avoids looking like the canvas is playing
    const processMutationSync = (e: CanvasEventWithTime, { replayer }: { replayer: Replayer }): void => {
        // We want to only process the most recent sync event
        handleQueue.set(e.data.id, [e, replayer])
        debouncedProcessQueuedEvents()
    }
    const debouncedProcessQueuedEvents = debounce(() => {
        Array.from(handleQueue.entries()).forEach(([id, [e, replayer]]) => {
            void (async () => {
                try {
                    await processMutation(e, replayer)
                    handleQueue.delete(id)
                } catch (e) {
                    handleMutationError(e)
                }
            })()
        })
    }, DEBOUNCE_MILLIS)

    const deserializeAndPreloadCanvasEvents = async (data: canvasMutationData, event: eventWithTime): Promise<void> => {
        if (!canvasEventMap.has(event)) {
            const status = { isUnchanged: true }

            if ('commands' in data) {
                const commands = await Promise.all(
                    data.commands.map(async (c) => {
                        const args = await Promise.all(
                            (c.args as CanvasArg[]).map(deserializeCanvasArg(imageMap, null, status))
                        )
                        return { ...c, args }
                    })
                )
                if (status.isUnchanged === false) {
                    canvasEventMap.set(event, { ...data, commands })
                }
            } else {
                const args = await Promise.all(
                    (data.args as CanvasArg[]).map(deserializeCanvasArg(imageMap, null, status))
                )
                if (status.isUnchanged === false) {
                    canvasEventMap.set(event, { ...data, args })
                }
            }
        }
    }

    const cloneCanvas = (id: number, node: HTMLCanvasElement): HTMLCanvasElement => {
        const cloneNode = node.cloneNode() as HTMLCanvasElement
        canvases.set(id, cloneNode)
        document.adoptNode(cloneNode)
        return cloneNode
    }

    const pruneBuffer = (event: eventWithTime): void => {
        while (pruneQueue.length) {
            const difference = Math.abs(event.timestamp - pruneQueue[0].timestamp)
            const eventToPrune = pruneQueue.shift()
            if (eventToPrune) {
                canvasEventMap.delete(eventToPrune)
            }
            if (difference <= BUFFER_TIME && pruneQueue.length <= PRELOAD_BUFFER_SIZE) {
                break
            }
        }
    }

    const processMutation = async (e: CanvasEventWithTime, replayer: Replayer): Promise<void> => {
        pruneBuffer(e)
        pruneQueue.push(e)
        void preload(e)

        const data = e.data as canvasMutationData
        const source = replayer.getMirror().getNode(data.id) as HTMLCanvasElement
        const target = canvases.get(data.id) || (source && cloneCanvas(data.id, source))

        if (!target) {
            return
        }

        if (source) {
            target.width = source.clientWidth || source.width
            target.height = source.clientHeight || source.height
        }

        await canvasMutation({
            event: e,
            mutation: data,
            target: target,
            imageMap,
            canvasEventMap,
            errorHandler: (error: unknown) => {
                handleMutationError(error)
            },
        })

        const img = containers.get(data.id)
        const originalCanvas = canvases.get(data.id)

        if (img && originalCanvas) {
            target.toBlob(
                (blob) => {
                    if (!blob) {
                        return
                    }

                    // Step 1: Get the canvas dimensions while it's still in the DOM
                    const canvasRect = originalCanvas.getBoundingClientRect()
                    const computedStyle = window.getComputedStyle(originalCanvas)

                    // Check if canvas uses percentage-based sizing
                    const usesPercentageWidth = computedStyle.width.includes('%')
                    const usesPercentageHeight = computedStyle.height.includes('%')

                    let finalWidthStyle: string
                    let finalHeightStyle: string

                    if (usesPercentageWidth) {
                        // Keep percentage width
                        finalWidthStyle = computedStyle.width
                    } else {
                        // Use measured or fallback pixel width
                        const measuredWidth =
                            canvasRect.width || originalCanvas.offsetWidth || originalCanvas.clientWidth
                        finalWidthStyle =
                            measuredWidth && measuredWidth >= 10
                                ? measuredWidth + 'px'
                                : (originalCanvas.width || 300) + 'px'
                    }

                    if (usesPercentageHeight) {
                        // Keep percentage height
                        finalHeightStyle = computedStyle.height
                    } else {
                        // Use measured or fallback pixel height
                        const measuredHeight =
                            canvasRect.height || originalCanvas.offsetHeight || originalCanvas.clientHeight
                        finalHeightStyle =
                            measuredHeight && measuredHeight >= 10
                                ? measuredHeight + 'px'
                                : (originalCanvas.height || 150) + 'px'
                    }

                    const url = URL.createObjectURL(blob)

                    /**
                     * Tracks all active ObjectURLs per rrweb node id (canvas/image container).
                     * Rationale:
                     * - URL.createObjectURL allocates; relying only on img.onload to revoke leaks if src is replaced before load fires.
                     * Strategy:
                     * - When generating a new frame, track its URL, set img.src to it, then revoke all other URLs for that id.
                     * - On load/error of the current frame, revoke that URL and remove it from the set.
                     * - When a set becomes empty, remove the id entry.
                     * Effect: prevents ObjectURL leaks and keeps memory bounded during fast updates/skip-inactivity bursts.
                     */
                    trackUrl(data.id, url)

                    img.onload = () => {
                        // Step 2: Apply the chosen dimensions and replace canvas

                        // Apply the chosen dimensions to the image
                        img.style.width = finalWidthStyle
                        img.style.height = finalHeightStyle
                        img.style.display = computedStyle.display || 'block'
                        img.style.objectFit = 'fill'

                        // Copy other layout-related styles from canvas
                        const layoutStyles = [
                            'margin',
                            'padding',
                            'border',
                            'boxSizing',
                            'position',
                            'top',
                            'left',
                            'right',
                            'bottom',
                        ]
                        layoutStyles.forEach((prop) => {
                            const value = computedStyle.getPropertyValue(prop)
                            if (value && value !== 'auto' && value !== 'normal') {
                                img.style.setProperty(prop, value)
                            }
                        })

                        // Replace the canvas with the properly sized image
                        const parent = originalCanvas.parentNode
                        if (parent) {
                            parent.replaceChild(img, originalCanvas)
                        }

                        finalizeUrl(data.id, url)
                    }
                    img.onerror = () => finalizeUrl(data.id, url)

                    img.src = url

                    // Now that the new src is applied, revoke everything else
                    revokeAllForIdExcept(data.id, url)
                },
                // ensures transparency is possible
                'image/webp',
                0.4
            )
        }
    }

    const preload = async (currentEvent?: CanvasEventWithTime): Promise<void> => {
        const currentIndex = nextPreloadIndex
            ? nextPreloadIndex
            : currentEvent
              ? quickFindClosestCanvasEventIndex(canvasMutationEvents, currentEvent, 0, canvasMutationEvents.length)
              : 0

        const eventsToPreload = canvasMutationEvents
            .slice(currentIndex, currentIndex + PRELOAD_BUFFER_SIZE)
            .filter(({ timestamp }) => !currentEvent || timestamp - currentEvent.timestamp <= BUFFER_TIME)

        nextPreloadIndex = currentIndex + 1

        for (const event of eventsToPreload) {
            await deserializeAndPreloadCanvasEvents(event.data as canvasMutationData, event)
        }
    }

    void preload()

    return {
        onBuild: (node, { id }) => {
            if (!node) {
                return
            }

            if (node.nodeName === 'CANVAS' && node.nodeType === 1) {
                const el = containers.get(id) || document.createElement('img')
                const canvasElement = node as HTMLCanvasElement

                // Copy attributes (including width/height for now)
                for (let i = 0; i < canvasElement.attributes.length; i++) {
                    const attr = canvasElement.attributes[i]
                    el.setAttribute(attr.name, attr.value)
                }

                // Store the image but don't replace the canvas yet
                containers.set(id, el)

                // Store reference to the original canvas for dimension calculation
                canvases.set(id, canvasElement)
            }
        },

        handler: (e: eventWithTime, isSync: boolean, { replayer }: { replayer: Replayer }) => {
            const isCanvas = isCanvasMutation(e)

            // scrubbing / fast forwarding
            if (isSync) {
                // reset preload index
                nextPreloadIndex = null
                canvasEventMap.clear()

                if (isCanvas) {
                    processMutationSync(e, { replayer })
                } else {
                    pruneBuffer(e)
                }
                pruneBuffer(e)
            } else if (isCanvas) {
                void processMutation(e, replayer).catch(handleMutationError)
            }
        },
    } as ReplayPlugin
}

const handleMutationError = (error: unknown): void => {
    posthog.captureException(error)
}

const objectUrlsById = new Map<number, Set<string>>()

const trackUrl = (id: number, url: string): void => {
    let set = objectUrlsById.get(id)
    if (!set) {
        set = new Set()
        objectUrlsById.set(id, set)
    }
    set.add(url)
}

const revokeAllForIdExcept = (id: number, keep?: string): void => {
    const set = objectUrlsById.get(id)
    if (!set) {
        return
    }
    for (const u of set) {
        if (keep && u === keep) {
            continue
        }
        URL.revokeObjectURL(u)
        set.delete(u)
    }
    if (set.size === 0) {
        objectUrlsById.delete(id)
    }
}

const finalizeUrl = (id: number, url: string): void => {
    // This runs on load/error. Revoke the url we just used and drop it from the set.
    URL.revokeObjectURL(url)
    const set = objectUrlsById.get(id)
    if (set) {
        set.delete(url)
        if (set.size === 0) {
            objectUrlsById.delete(id)
        }
    }
}
