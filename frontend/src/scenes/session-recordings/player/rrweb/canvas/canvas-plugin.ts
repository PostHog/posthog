import { CanvasArg, canvasMutationData, canvasMutationParam, eventWithTime } from '@rrweb/types'
import { captureException } from '@sentry/react'
import { debounce } from 'lib/utils'
import { canvasMutation, EventType, IncrementalSource, Replayer } from 'rrweb'
import { ReplayPlugin } from 'rrweb/typings/types'

import { deserializeCanvasArg } from './deserialize-canvas-args'

type CanvasEventWithTime = eventWithTime & {
    type: EventType.IncrementalSnapshot
    data: canvasMutationData
}

function isCanvasMutation(e: eventWithTime): e is CanvasEventWithTime {
    return e.type === EventType.IncrementalSnapshot && e.data.source === IncrementalSource.CanvasMutation
}

function findEvent(events: CanvasEventWithTime[], target: CanvasEventWithTime): number {
    return events.findIndex((event) => event.data.id === target.data.id)
}

const PRELOAD_BUFFER_SIZE = 20
const BUFFER_TIME = 30000 // 30 seconds

export const CanvasReplayerPlugin = (events: eventWithTime[]): ReplayPlugin => {
    const canvases = new Map<number, HTMLCanvasElement>([])
    const containers = new Map<number, HTMLImageElement>([])
    const imageMap = new Map<eventWithTime | string, HTMLImageElement>()
    const canvasEventMap = new Map<eventWithTime | string, canvasMutationParam>()
    const preloadBuffer = new Set<CanvasEventWithTime>()
    const pruneQueue: eventWithTime[] = []
    let nextPreloadIndex: number | null = null
    let latestCanvasEvent: CanvasEventWithTime | null = null

    const canvasMutationEvents = events.filter(isCanvasMutation)

    // Buffers mutations from user interactions before Replayer was ready
    const handleQueue = new Map<number, [CanvasEventWithTime, Replayer]>()
    const flushQueue = (id: number): void => {
        const queueItem = handleQueue.get(id)
        handleQueue.delete(id)
        if (!queueItem) {
            return
        }
        const [event, replayer] = queueItem
        processMutation(event, replayer).catch(handleMutationError)
    }

    // only processes a single mutation event in cases when the user is scrubbing
    // avoids looking like the canvas is playing
    const processMutationSync = (e: CanvasEventWithTime, { replayer }: { replayer: Replayer }): void => {
        // We want to only process the most recent sync event
        handleQueue.set(e.data.id, [e, replayer])
        debouncedProcessQueuedEvents()
    }
    const debouncedProcessQueuedEvents = debounce(
        () => {
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
        },
        250 // currently using 4fps for all recordings
    )

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
            if (difference <= BUFFER_TIME && pruneQueue.length <= PRELOAD_BUFFER_SIZE) {
                break
            }

            const eventToPrune = pruneQueue.shift()
            if (eventToPrune && isCanvasMutation(eventToPrune) && canvasEventMap.has(eventToPrune)) {
                canvasEventMap.delete(eventToPrune)
            }
        }

        pruneQueue.push(event)
    }

    const processMutation = async (e: CanvasEventWithTime, replayer: Replayer): Promise<void> => {
        const data = e.data as canvasMutationData
        const source = replayer.getMirror().getNode(data.id) as HTMLCanvasElement
        const target = canvases.get(data.id) || (source && cloneCanvas(data.id, source))

        if (!target) {
            return
        }

        if (source) {
            target.width = source.clientWidth
            target.height = source.clientHeight
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
                'image/jpeg',
                0.5
            )
        }
    }

    const preload = async (currentEvent?: CanvasEventWithTime): Promise<void> => {
        const currentIndex = nextPreloadIndex
            ? nextPreloadIndex
            : currentEvent
            ? findEvent(canvasMutationEvents, currentEvent)
            : 0

        const eventsToPreload = canvasMutationEvents.slice(
            currentIndex,
            currentIndex + PRELOAD_BUFFER_SIZE - preloadBuffer.size
        )

        nextPreloadIndex = currentIndex + 1

        for (const event of eventsToPreload) {
            if (!preloadBuffer.has(event) && !canvasEventMap.has(event)) {
                preloadBuffer.add(event)
                await deserializeAndPreloadCanvasEvents(event.data as canvasMutationData, event)
                preloadBuffer.delete(event)
            }
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
                ;(node as HTMLCanvasElement).appendChild(el)
                containers.set(id, el)
            }

            // `handler` can be called by users seeking before Replayer is ready
            // replays user interactions stored in queue from before DOM was built
            flushQueue(id)
        },

        // eslint-disable-next-line @typescript-eslint/no-misused-promises
        handler: async (e: eventWithTime, isSync: boolean, { replayer }: { replayer: Replayer }) => {
            const isCanvas = isCanvasMutation(e)

            if (!isCanvas) {
                if (latestCanvasEvent) {
                    void processMutation(latestCanvasEvent, replayer)
                }
                pruneBuffer(e)
                return
            }

            // scrubbing / fast forwarding
            if (isSync) {
                // reset preload index
                nextPreloadIndex = null
                latestCanvasEvent = e
                processMutationSync(e, { replayer })
                pruneBuffer(e)
            } else {
                void processMutation(e, replayer).catch(handleMutationError)
            }
        },
    } as ReplayPlugin
}

const handleMutationError = (error: unknown): void => {
    if (error instanceof Error) {
        captureException(error)
    } else {
        console.error(error)
    }
}
