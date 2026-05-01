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

import { debounce } from '../utils'
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

export type CanvasPluginErrorHandler = (error: unknown) => void

const noOpErrorHandler: CanvasPluginErrorHandler = () => {}

export const CanvasReplayerPlugin = (
    events: eventWithTime[],
    onError: CanvasPluginErrorHandler = noOpErrorHandler
): ReplayPlugin & { destroy: () => void } => {
    const canvases = new Map<number, HTMLCanvasElement>([])
    const containers = new Map<number, HTMLImageElement>([])
    const imageMap = new Map<eventWithTime | string, HTMLImageElement>()
    const canvasEventMap = new Map<eventWithTime | string, canvasMutationParam>()
    const pruneQueue: eventWithTime[] = []
    let nextPreloadIndex: number | null = null
    let destroyed = false

    const canvasMutationEvents = events.filter(isCanvasMutation)

    const handleQueue = new Map<number, [CanvasEventWithTime, Replayer]>()

    const processMutationSync = (e: CanvasEventWithTime, { replayer }: { replayer: Replayer }): void => {
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
                    onError(e)
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

    const objectUrlsById = new Map<number, Set<string>>()
    const controllerById = new Map<number, AbortController>()

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
        URL.revokeObjectURL(url)
        const set = objectUrlsById.get(id)
        if (set) {
            set.delete(url)
            if (set.size === 0) {
                objectUrlsById.delete(id)
            }
        }
    }

    const abortPreviousListeners = (id: number): void => {
        const controller = controllerById.get(id)
        if (controller) {
            controller.abort()
            controllerById.delete(id)
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
            let snapshotWidth = 0
            let snapshotHeight = 0

            const displayWidth = 'displayWidth' in data ? (data.displayWidth as number) : 0
            const displayHeight = 'displayHeight' in data ? (data.displayHeight as number) : 0
            if (displayWidth && displayHeight) {
                snapshotWidth = displayWidth
                snapshotHeight = displayHeight
            } else if ('commands' in data && data.commands.length > 0) {
                const firstCmd = data.commands[0]
                if (firstCmd.property === 'clearRect' && firstCmd.args?.length >= 4) {
                    snapshotWidth = firstCmd.args[2] as number
                    snapshotHeight = firstCmd.args[3] as number
                }
            }

            target.width = snapshotWidth || source.clientWidth || source.width
            target.height = snapshotHeight || source.clientHeight || source.height
        }

        await canvasMutation({
            event: e,
            mutation: data,
            target: target,
            imageMap,
            canvasEventMap,
            errorHandler: (error: unknown) => {
                onError(error)
            },
        })

        const img = containers.get(data.id)
        const originalCanvas = canvases.get(data.id)

        if (img && originalCanvas) {
            target.toBlob(
                (blob) => {
                    if (!blob || destroyed) {
                        return
                    }

                    const canvasRect = originalCanvas.getBoundingClientRect()
                    const computedStyle = window.getComputedStyle(originalCanvas)

                    const usesPercentageWidth = computedStyle.width.includes('%')
                    const usesPercentageHeight = computedStyle.height.includes('%')

                    let finalWidthStyle: string
                    let finalHeightStyle: string

                    if (usesPercentageWidth) {
                        finalWidthStyle = computedStyle.width
                    } else {
                        const measuredWidth =
                            canvasRect.width || originalCanvas.offsetWidth || originalCanvas.clientWidth
                        finalWidthStyle =
                            measuredWidth && measuredWidth >= 10
                                ? measuredWidth + 'px'
                                : (originalCanvas.width || 300) + 'px'
                    }

                    if (usesPercentageHeight) {
                        finalHeightStyle = computedStyle.height
                    } else {
                        const measuredHeight =
                            canvasRect.height || originalCanvas.offsetHeight || originalCanvas.clientHeight
                        finalHeightStyle =
                            measuredHeight && measuredHeight >= 10
                                ? measuredHeight + 'px'
                                : (originalCanvas.height || 150) + 'px'
                    }

                    const url = URL.createObjectURL(blob)

                    trackUrl(data.id, url)
                    abortPreviousListeners(data.id)

                    const controller = new AbortController()
                    controllerById.set(data.id, controller)

                    img.addEventListener(
                        'load',
                        () => {
                            img.style.width = finalWidthStyle
                            img.style.height = finalHeightStyle
                            img.style.display = computedStyle.display || 'block'
                            img.style.objectFit = 'fill'

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

                            const parent = originalCanvas.parentNode
                            if (parent) {
                                parent.replaceChild(img, originalCanvas)
                            }

                            finalizeUrl(data.id, url)
                            controllerById.delete(data.id)
                        },
                        { signal: controller.signal }
                    )
                    img.addEventListener(
                        'error',
                        () => {
                            finalizeUrl(data.id, url)
                            controllerById.delete(data.id)
                        },
                        { signal: controller.signal }
                    )

                    img.src = url

                    revokeAllForIdExcept(data.id, url)
                },
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

                for (let i = 0; i < canvasElement.attributes.length; i++) {
                    const attr = canvasElement.attributes[i]
                    el.setAttribute(attr.name, attr.value)
                }

                containers.set(id, el)
                canvases.set(id, canvasElement)
            }
        },

        handler: (e: eventWithTime, isSync: boolean, { replayer }: { replayer: Replayer }) => {
            const isCanvas = isCanvasMutation(e)

            if (isSync) {
                nextPreloadIndex = null
                canvasEventMap.clear()

                if (isCanvas) {
                    processMutationSync(e, { replayer })
                } else {
                    pruneBuffer(e)
                }
                pruneBuffer(e)
            } else if (isCanvas) {
                void processMutation(e, replayer).catch(onError)
            }
        },

        destroy: () => {
            destroyed = true

            for (const controller of controllerById.values()) {
                controller.abort()
            }
            controllerById.clear()

            for (const [id] of objectUrlsById) {
                revokeAllForIdExcept(id)
            }
            objectUrlsById.clear()

            canvases.clear()
            containers.clear()
            imageMap.clear()
            canvasEventMap.clear()
            handleQueue.clear()
            pruneQueue.length = 0
            nextPreloadIndex = null
        },
    }
}
