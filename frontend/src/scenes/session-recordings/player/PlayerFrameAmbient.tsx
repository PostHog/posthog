import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import {
    AmbientFrameSampler,
    AmbientGrid,
    Rect,
    extendGrid,
    isBoxed,
    sameGrid,
} from 'scenes/session-recordings/player/playerFrameAmbientSampling'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const CHECK_INTERVAL_MS = 500
// Overhang the container, so the blur does not fade to the dark background at the edges.
const OVERHANG = 0.1

interface AmbientLayer {
    grid: AmbientGrid
    area: Rect
}

// Two canvases cross-fade, so a page change eases in instead of cutting.
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
        // Sampling reads layout in the recorded page, so it runs only after something there could have changed.
        let dirty = true
        let observedDocument: Document | null = null
        let lastLayout = ''
        const markDirty = (): void => {
            dirty = true
        }
        const observer = new MutationObserver(markDirty)

        const show = (next: AmbientLayer | null): void => {
            if (sameGrid(next?.grid ?? null, current?.grid ?? null)) {
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

        // rrweb replaces the recorded document on every full snapshot, so the observer follows it.
        const observe = (recordedDocument: Document): void => {
            if (recordedDocument === observedDocument) {
                return
            }
            observer.disconnect()
            observedDocument?.removeEventListener('scroll', markDirty, true)
            observer.observe(recordedDocument, {
                subtree: true,
                childList: true,
                attributes: true,
                characterData: true,
            })
            recordedDocument.addEventListener('scroll', markDirty, true)
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
            dirty = false
            const sampled = isBoxed(container, scaled) ? sampler.sample(recordedDocument, recording) : null
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

        sampler.onBackgroundImageLoad = markDirty
        update()
        const interval = setInterval(update, CHECK_INTERVAL_MS)
        return () => {
            clearInterval(interval)
            observer.disconnect()
            observedDocument?.removeEventListener('scroll', markDirty, true)
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
