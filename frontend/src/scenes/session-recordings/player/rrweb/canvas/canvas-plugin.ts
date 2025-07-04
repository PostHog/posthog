import { canvasMutation, Replayer } from '@posthog/rrweb'
import { ReplayPlugin } from '@posthog/rrweb'
import {
    CanvasArg,
    canvasMutationData,
    canvasMutationParam,
    EventType,
    eventWithTime,
    IncrementalSource,
} from '@posthog/rrweb-types'
import { debounce } from 'lib/utils'
import posthog from 'posthog-js'

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
        if (img) {
            target.toBlob(
                (blob) => {
                    if (blob) {
                        img.style.width = 'initial'
                        img.style.height = 'initial'

                        const url = URL.createObjectURL(blob)
                        // no longer need to read the blob so it's revoked
                        img.onload = () => URL.revokeObjectURL(url)
                        img.src = url
                    }
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
                const parent = node.parentNode as Node
                parent?.replaceChild?.(el, node as Node)
                containers.set(id, el)
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
