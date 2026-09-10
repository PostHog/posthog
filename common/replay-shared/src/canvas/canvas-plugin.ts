import { Replayer, canvasMutation } from 'posthog-js/rrweb'
import { ReplayPlugin } from 'posthog-js/rrweb'
import {
    CanvasArg,
    EventType,
    IncrementalSource,
    canvasMutationData,
    canvasMutationParam,
    eventWithTime,
} from 'posthog-js/rrweb-types'

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

// The reconstructed <img> lives in the top-level document, so it inherits only
// presentational attributes from the recorded canvas. Skip inline event handlers
// (every handler is named `on<event>`, so this covers the whole class) and the
// URL-loading attributes — the plugin points `src` at the rendered canvas blob
// itself, so a copied `src`/`srcset` would only fetch an attacker-controlled URL.
function isCopyableAttribute(name: string): boolean {
    const lowered = name.toLowerCase()
    return !lowered.startsWith('on') && lowered !== 'src' && lowered !== 'srcset'
}

export const CanvasReplayerPlugin = (
    events: eventWithTime[],
    onError: CanvasPluginErrorHandler = noOpErrorHandler
): ReplayPlugin & { destroy: () => void } => {
    const canvases = new Map<number, HTMLCanvasElement>([])
    const containers = new Map<number, HTMLImageElement>([])
    const imageMap = new Map<eventWithTime | string, HTMLImageElement>()
    const canvasEventMap = new Map<eventWithTime | string, canvasMutationParam>()
    const pruneQueue: eventWithTime[] = []
    const attributeObservers = new Map<number, MutationObserver>()
    const presentationStyles = new Map<number, Record<string, string>>()
    let nextPreloadIndex: number | null = null
    let destroyed = false

    // The styles the plugin itself puts on the <img> to make it stand in for the canvas,
    // measured from the live canvas each painted frame. A full apply, so a canvas that
    // resizes between frames updates to the newly measured size.
    const applyPresentationStyles = (id: number): void => {
        const img = containers.get(id)
        const styles = presentationStyles.get(id)
        if (img && styles) {
            Object.assign(img.style, styles)
        }
    }

    // Restore the presentation styles after a copied `style` attribute wiped the inline
    // style, but keep the recorded style authoritative: only fill in a property the
    // recording did not set. A full re-apply would revert a later inline change the page
    // makes to hide or reveal the canvas (e.g. `display: none`) to the frame-time value.
    const fillMissingPresentationStyles = (id: number): void => {
        const img = containers.get(id)
        const styles = presentationStyles.get(id)
        if (!img || !styles) {
            return
        }
        const style = img.style as unknown as Record<string, string>
        for (const [property, value] of Object.entries(styles)) {
            if (!style[property]) {
                style[property] = value
            }
        }
    }

    const copyAttribute = (id: number, canvas: HTMLCanvasElement, img: HTMLImageElement, name: string): void => {
        if (!isCopyableAttribute(name)) {
            return
        }
        const value = canvas.getAttribute(name)
        if (value === null) {
            img.removeAttribute(name)
        } else {
            img.setAttribute(name, value)
        }
        if (name.toLowerCase() === 'style') {
            fillMissingPresentationStyles(id)
        }
    }

    const copyAttributes = (id: number, canvas: HTMLCanvasElement, img: HTMLImageElement): void => {
        // A backward seek rebuilds the id and reuses the same <img>, so it can still carry a
        // copyable attribute the rebuilt canvas no longer has. Drop those first; copyAttribute
        // removes the absent attribute and re-applies the presentation styles when it clears style.
        for (const { name } of Array.from(img.attributes)) {
            if (isCopyableAttribute(name) && !canvas.hasAttribute(name)) {
                copyAttribute(id, canvas, img, name)
            }
        }
        for (const { name } of Array.from(canvas.attributes)) {
            copyAttribute(id, canvas, img, name)
        }
    }

    // The recorded canvas stays in the replayer's mirror and keeps receiving attribute
    // mutations after the <img> has replaced it in the document, so mirror them across.
    // Without this, a canvas that the page hides while it paints (react-pdf does this)
    // is never revealed on playback: the reveal lands on the replaced canvas.
    const trackAttributes = (id: number, canvas: HTMLCanvasElement, img: HTMLImageElement): void => {
        attributeObservers.get(id)?.disconnect()
        const observer = new MutationObserver((records) => {
            for (const record of records) {
                if (record.attributeName) {
                    copyAttribute(id, canvas, img, record.attributeName)
                }
            }
        })
        observer.observe(canvas, { attributes: true })
        attributeObservers.set(id, observer)
    }

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
                            const styles: Record<string, string> = {
                                width: finalWidthStyle,
                                height: finalHeightStyle,
                                display: computedStyle.display || 'block',
                                objectFit: 'fill',
                            }

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
                                    styles[prop] = value
                                }
                            })

                            presentationStyles.set(data.id, styles)
                            applyPresentationStyles(data.id)

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

                containers.set(id, el)
                canvases.set(id, canvasElement)
                copyAttributes(id, canvasElement, el)
                trackAttributes(id, canvasElement, el)
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

            for (const observer of attributeObservers.values()) {
                observer.disconnect()
            }
            attributeObservers.clear()
            presentationStyles.clear()

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
