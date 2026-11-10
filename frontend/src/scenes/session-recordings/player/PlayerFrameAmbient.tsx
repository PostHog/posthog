import clsx from 'clsx'
import { useValues } from 'kea'
import { EventType, Handler, IncrementalSource, eventWithTime } from 'posthog-js/rrweb-types'
import { useEffect, useRef } from 'react'

import {
    AmbientBlend,
    AmbientFrameSampler,
    Rect,
    extendGrid,
    isBoxed,
} from 'scenes/session-recordings/player/playerFrameAmbientSampling'
import { getPlayerFrameScale } from 'scenes/session-recordings/player/playerFrameScaling'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const CHECK_INTERVAL_MS = 1000
const MIN_PAINT_INTERVAL_MS = 50
// Stylesheet changes replay through the CSSOM, which the mutation observer cannot see.
const STYLESHEET_SOURCES = [
    IncrementalSource.StyleSheetRule,
    IncrementalSource.StyleDeclaration,
    IncrementalSource.AdoptedStyleSheet,
]
const OVERHANG = 0.1

export function PlayerFrameAmbient(): JSX.Element | null {
    const { player, showAmbientBackground, maskingWindow, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    // These outlive the player, because it is rebuilt several times while one recording loads.
    const blendRef = useRef(new AmbientBlend())
    const samplerRef = useRef(new AmbientFrameSampler())
    const maskedRef = useRef(maskingWindow)
    maskedRef.current = maskingWindow

    useEffect(() => {
        blendRef.current = new AmbientBlend()
        samplerRef.current = new AmbientFrameSampler()
        canvasRef.current?.style.setProperty('opacity', '0')
    }, [sessionRecordingId])

    useEffect(() => {
        const replayer = player?.replayer
        const canvas = canvasRef.current
        const context = canvas?.getContext('2d')
        if (!showAmbientBackground || !replayer || !canvas || !context) {
            return
        }
        const sampler = samplerRef.current
        const blend = blendRef.current
        const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
        let dirty = true
        let observedDocument: Document | null = null
        let lastLayout = ''
        let animationFrame = 0
        let rebuildFrame = 0
        let lastPaintTime = 0
        // The blend outlives the canvas, so a canvas mounted by turning the setting back on starts empty.
        let canvasSized = false
        const markDirty = (): void => {
            dirty = true
        }
        const observer = new MutationObserver(markDirty)

        const paint = (): void => {
            context.putImageData(blend.imageData(), 0, 0)
        }

        const animate = (time: number): void => {
            if (time - lastPaintTime < MIN_PAINT_INTERVAL_MS) {
                animationFrame = requestAnimationFrame(animate)
                return
            }
            lastPaintTime = time
            const { changed, settled } = blend.step(time)
            if (changed) {
                paint()
            }
            animationFrame = settled ? 0 : requestAnimationFrame(animate)
        }

        const placeCanvas = (area: Rect): void => {
            Object.assign(canvas.style, {
                left: `${area.left}px`,
                top: `${area.top}px`,
                width: `${area.width}px`,
                height: `${area.height}px`,
            })
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
            const container = replayer.wrapper.ownerDocument.body.getBoundingClientRect()
            if (
                document.hidden ||
                maskedRef.current ||
                !recordedDocument ||
                !(recording.width >= 1 && recording.height >= 1) ||
                !(container.width >= 1 && container.height >= 1)
            ) {
                return
            }
            observe(recordedDocument)
            // Computed as PlayerFrame does, because the wrapper's measured size lags until its scale applies.
            const { scale } = getPlayerFrameScale(container, recording)
            const width = recording.width * scale
            const height = recording.height * scale
            const scaled = {
                width,
                height,
                left: (container.width - width) / 2,
                top: (container.height - height) / 2,
            }
            if (!isBoxed(container, scaled)) {
                canvas.style.opacity = '0'
                lastLayout = ''
                return
            }
            const layout = [container.width, container.height, recording.width, recording.height].join()
            if (layout !== lastLayout) {
                lastLayout = layout
                dirty = true
            }
            if (!dirty) {
                return
            }
            // A document mid-rebuild samples as nothing, so the last colors stay up until a real sample replaces them.
            const sampled = sampler.sample(recordedDocument, recording)
            if (!sampled) {
                return
            }
            dirty = sampler.sawCanvas
            const overhang = { x: container.width * OVERHANG, y: container.height * OVERHANG }
            const extended = extendGrid(sampled, scaled, {
                left: -overhang.x,
                top: -overhang.y,
                width: container.width + 2 * overhang.x,
                height: container.height + 2 * overhang.y,
            })
            placeCanvas(extended.area)
            if (blend.setTarget(extended.grid) || !canvasSized) {
                canvasSized = true
                canvas.width = blend.columns
                canvas.height = blend.rows
                paint()
            } else if (reducedMotion) {
                blend.snap()
                paint()
            } else if (!animationFrame) {
                animationFrame = requestAnimationFrame(animate)
            }
            canvas.style.opacity = '1'
        }

        const markDirtyOnStyleChange = (event: eventWithTime): void => {
            if (event.type === EventType.IncrementalSnapshot && STYLESHEET_SOURCES.includes(event.data.source)) {
                dirty = true
            }
        }
        // rrweb applies the events up to a seek target in the same task, so the sample waits for the next frame.
        const sampleAfterRebuild = (): void => {
            dirty = true
            rebuildFrame ||= requestAnimationFrame(() => {
                rebuildFrame = 0
                update()
            })
        }
        replayer.on('event-cast', markDirtyOnStyleChange as Handler)
        replayer.on('fullsnapshot-rebuilded', sampleAfterRebuild as Handler)
        sampler.onBackgroundImageLoad = markDirty
        update()
        const interval = setInterval(update, CHECK_INTERVAL_MS)
        return () => {
            clearInterval(interval)
            cancelAnimationFrame(animationFrame)
            cancelAnimationFrame(rebuildFrame)
            replayer.off('event-cast', markDirtyOnStyleChange as Handler)
            replayer.off('fullsnapshot-rebuilded', sampleAfterRebuild as Handler)
            sampler.onBackgroundImageLoad = null
            observer.disconnect()
            observedDocument?.removeEventListener('scroll', markDirty, true)
            observedDocument?.removeEventListener('load', markDirty, true)
        }
    }, [player, showAmbientBackground, sessionRecordingId])

    if (!showAmbientBackground) {
        return null
    }

    // Hidden rather than unmounted while the window is masked, so the colors are still there when it lifts.
    return (
        <div className="PlayerFrame__ambient" aria-hidden>
            <canvas
                ref={canvasRef}
                className={clsx('PlayerFrame__ambient-layer', maskingWindow && 'PlayerFrame__ambient-layer--hidden')}
            />
        </div>
    )
}
