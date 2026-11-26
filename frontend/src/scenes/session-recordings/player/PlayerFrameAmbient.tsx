import clsx from 'clsx'
import { useValues } from 'kea'
import { EventType, Handler, IncrementalSource, eventWithTime } from 'posthog-js/rrweb-types'
import { useEffect, useRef } from 'react'

import {
    AmbientBlend,
    AmbientFrameSampler,
    AmbientGrid,
    Rect,
    extendGrid,
    isBoxed,
    scaledFrameRect,
} from 'scenes/session-recordings/player/playerFrameAmbientSampling'
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
        const motionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)')
        let reducedMotion = motionQuery?.matches ?? false
        const onMotionChange = (event: MediaQueryListEvent): void => {
            reducedMotion = event.matches
            if (reducedMotion && animationFrame) {
                cancelAnimationFrame(animationFrame)
                animationFrame = 0
                blend.snap()
                paint()
            }
        }
        motionQuery?.addEventListener('change', onMotionChange)
        let dirty = true
        // The rebuild event, not the body's content, marks a sampleable page, because a real page can have an empty body.
        let rebuilt = !!replayer.iframe?.contentDocument?.body?.hasChildNodes()
        let observedDocument: Document | null = null
        let lastLayout = ''
        let animationFrame = 0
        let rebuildFrame = 0
        let lastPaintTime = 0
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
            // rrweb's document.open() on each full snapshot drops these non-bubbling listeners, so every check re-adds them.
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

        const show = (grid: AmbientGrid, area: Rect): void => {
            placeCanvas(area)
            const snapped = blend.setTarget(grid)
            if (snapped || !canvasSized) {
                canvasSized = true
                canvas.width = blend.columns
                canvas.height = blend.rows
                paint()
            }
            if (!snapped && reducedMotion) {
                blend.snap()
                paint()
            } else if (!snapped && !animationFrame) {
                animationFrame = requestAnimationFrame(animate)
            }
            canvas.style.opacity = '1'
        }

        const update = (): void => {
            const iframe = replayer.iframe
            const recordedDocument = iframe?.contentDocument
            const recording = { width: Number(iframe?.width), height: Number(iframe?.height) }
            const container = replayer.wrapper.ownerDocument.body.getBoundingClientRect()
            const scaled = scaledFrameRect(container, recording)
            if (document.hidden || maskedRef.current || !rebuilt || !recordedDocument || !scaled) {
                return
            }
            observe(recordedDocument)
            if (!isBoxed(container, scaled)) {
                canvas.style.opacity = '0'
                lastLayout = ''
                return
            }
            const layout = [container.width, container.height, recording.width, recording.height].join()
            dirty ||= layout !== lastLayout
            lastLayout = layout
            const sampled = dirty ? sampler.sample(recordedDocument, recording) : null
            if (!sampled) {
                return
            }
            dirty = sampler.needsResample
            const overhang = { x: container.width * OVERHANG, y: container.height * OVERHANG }
            const extended = extendGrid(sampled, scaled, {
                left: -overhang.x,
                top: -overhang.y,
                width: container.width + 2 * overhang.x,
                height: container.height + 2 * overhang.y,
            })
            show(extended.grid, extended.area)
        }

        const markDirtyOnStyleChange = (event: eventWithTime): void => {
            if (event.type === EventType.IncrementalSnapshot && STYLESHEET_SOURCES.includes(event.data.source)) {
                dirty = true
            }
        }
        // rrweb applies the events up to a seek target in the same task, so the sample waits for the next frame.
        const sampleAfterRebuild = (): void => {
            rebuilt = true
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
            motionQuery?.removeEventListener('change', onMotionChange)
            observer.disconnect()
            observedDocument?.removeEventListener('scroll', markDirty, true)
            observedDocument?.removeEventListener('load', markDirty, true)
        }
    }, [player, showAmbientBackground, sessionRecordingId])

    if (!showAmbientBackground) {
        return null
    }

    return (
        <div className="PlayerFrame__ambient" aria-hidden>
            <canvas
                ref={canvasRef}
                className={clsx('PlayerFrame__ambient-layer', maskingWindow && 'PlayerFrame__ambient-layer--hidden')}
            />
        </div>
    )
}
