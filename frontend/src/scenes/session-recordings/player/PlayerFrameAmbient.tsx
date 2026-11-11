import { useValues } from 'kea'
import { EventType, Handler, IncrementalSource, eventWithTime } from 'posthog-js/rrweb-types'
import { useEffect, useRef } from 'react'

import {
    AmbientFrameSampler,
    AmbientGrid,
    Rect,
    extendGrid,
    isBoxed,
    sameLayer,
} from 'scenes/session-recordings/player/playerFrameAmbientSampling'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const CHECK_INTERVAL_MS = 500
// Stylesheet changes replay through the CSSOM, which the mutation observer cannot see.
const STYLESHEET_SOURCES = [
    IncrementalSource.StyleSheetRule,
    IncrementalSource.StyleDeclaration,
    IncrementalSource.AdoptedStyleSheet,
]
const OVERHANG = 0.1

interface AmbientLayer {
    grid: AmbientGrid
    area: Rect
}

export function PlayerFrameAmbient(): JSX.Element | null {
    const { player, showAmbientBackground } = useValues(sessionRecordingPlayerLogic)
    const firstCanvas = useRef<HTMLCanvasElement | null>(null)
    const secondCanvas = useRef<HTMLCanvasElement | null>(null)

    useEffect(() => {
        const replayer = player?.replayer
        const first = firstCanvas.current
        const second = secondCanvas.current
        if (!showAmbientBackground || !replayer || !first || !second) {
            return
        }
        const canvases = [first, second]
        const sampler = new AmbientFrameSampler()
        let activeCanvas = 0
        let current: AmbientLayer | null = null
        let dirty = true
        let observedDocument: Document | null = null
        let lastLayout = ''
        const markDirty = (): void => {
            dirty = true
        }
        const observer = new MutationObserver(markDirty)

        const show = (next: AmbientLayer | null): void => {
            if (sameLayer(next, current)) {
                return
            }
            current = next
            const incoming = canvases[1 - activeCanvas]
            if (next) {
                Object.assign(incoming.style, {
                    left: `${next.area.left}px`,
                    top: `${next.area.top}px`,
                    width: `${next.area.width}px`,
                    height: `${next.area.height}px`,
                })
                incoming.width = next.grid.columns
                incoming.height = next.grid.rows
                incoming
                    .getContext('2d')
                    ?.putImageData(new ImageData(next.grid.pixels, next.grid.columns, next.grid.rows), 0, 0)
            }
            incoming.style.opacity = next ? '1' : '0'
            canvases[activeCanvas].style.opacity = '0'
            activeCanvas = 1 - activeCanvas
        }

        const observe = (recordedDocument: Document): void => {
            // rrweb's document.open() on each full snapshot drops listeners, so they are re-added every check.
            // Neither event bubbles, so they are caught on the way down.
            recordedDocument.addEventListener('scroll', markDirty, true)
            recordedDocument.addEventListener('load', markDirty, true)
            if (recordedDocument === observedDocument) {
                return
            }
            observer.disconnect()
            observedDocument?.removeEventListener('scroll', markDirty, true)
            observedDocument?.removeEventListener('load', markDirty, true)
            observer.observe(recordedDocument, {
                subtree: true,
                childList: true,
                attributes: true,
                characterData: true,
            })
            observedDocument = recordedDocument
            dirty = true
        }

        const update = (): void => {
            const iframe = replayer.iframe
            const recordedDocument = iframe?.contentDocument
            const recording = { width: Number(iframe?.width), height: Number(iframe?.height) }
            if (document.hidden || !recordedDocument || !recording.width || !recording.height) {
                return
            }
            observe(recordedDocument)
            const container = replayer.wrapper.ownerDocument.body.getBoundingClientRect()
            const scaled = replayer.wrapper.getBoundingClientRect()
            const layout = [
                container.width,
                container.height,
                scaled.left,
                scaled.top,
                scaled.width,
                scaled.height,
            ].join()
            if (layout !== lastLayout) {
                lastLayout = layout
                dirty = true
            }
            if (!dirty) {
                return
            }
            const sampled = isBoxed(container, scaled) ? sampler.sample(recordedDocument, recording) : null
            dirty = sampler.sawCanvas
            if (!sampled) {
                show(null)
                return
            }
            const overhang = { x: container.width * OVERHANG, y: container.height * OVERHANG }
            show(
                extendGrid(
                    sampled,
                    {
                        left: scaled.left - container.left,
                        top: scaled.top - container.top,
                        width: scaled.width,
                        height: scaled.height,
                    },
                    {
                        left: -overhang.x,
                        top: -overhang.y,
                        width: container.width + 2 * overhang.x,
                        height: container.height + 2 * overhang.y,
                    }
                )
            )
        }

        const markDirtyOnStyleChange = (event: eventWithTime): void => {
            if (event.type === EventType.IncrementalSnapshot && STYLESHEET_SOURCES.includes(event.data.source)) {
                dirty = true
            }
        }
        replayer.on('event-cast', markDirtyOnStyleChange as Handler)
        sampler.onBackgroundImageLoad = markDirty
        update()
        const interval = setInterval(update, CHECK_INTERVAL_MS)
        return () => {
            clearInterval(interval)
            replayer.off('event-cast', markDirtyOnStyleChange as Handler)
            observer.disconnect()
            observedDocument?.removeEventListener('scroll', markDirty, true)
            observedDocument?.removeEventListener('load', markDirty, true)
            canvases.forEach((canvas) => canvas.style.setProperty('opacity', '0'))
        }
    }, [player, showAmbientBackground])

    if (!showAmbientBackground) {
        return null
    }

    return (
        <div className="PlayerFrame__ambient" aria-hidden>
            <canvas ref={firstCanvas} className="PlayerFrame__ambient-layer" />
            <canvas ref={secondCanvas} className="PlayerFrame__ambient-layer" />
        </div>
    )
}
