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
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const SAMPLE_INTERVAL_MS = 500
// Overhang the container, so the blur does not fade to the dark background at the edges.
const OVERHANG = 0.1

// Exported frames feed video rendering and analysis, which want the recording on plain bars.
const MODES_WITHOUT_AMBIENT = [SessionRecordingPlayerMode.Screenshot, SessionRecordingPlayerMode.Video]

// Two canvases cross-fade, so a page change eases in instead of cutting.
export function PlayerFrameAmbient(): JSX.Element | null {
    const {
        player,
        maskingWindow,
        ambientBackground,
        logicProps: { mode },
    } = useValues(sessionRecordingPlayerLogic)
    const firstLayer = useRef<HTMLCanvasElement | null>(null)
    const secondLayer = useRef<HTMLCanvasElement | null>(null)

    const enabled = ambientBackground && !maskingWindow && !(mode && MODES_WITHOUT_AMBIENT.includes(mode))

    useEffect(() => {
        const replayer = player?.replayer
        const layers = [firstLayer.current, secondLayer.current]
        if (!enabled || !replayer || !layers[0] || !layers[1]) {
            return
        }
        const sampler = new AmbientFrameSampler()
        let activeLayer = 0
        let currentGrid: AmbientGrid | null = null

        const show = (grid: AmbientGrid | null, area?: Rect): void => {
            if (sameGrid(grid, currentGrid)) {
                return
            }
            currentGrid = grid
            const next = layers[1 - activeLayer] as HTMLCanvasElement
            const previous = layers[activeLayer] as HTMLCanvasElement
            if (grid && area) {
                next.style.left = `${area.left}px`
                next.style.top = `${area.top}px`
                next.style.width = `${area.width}px`
                next.style.height = `${area.height}px`
                next.width = grid.columns
                next.height = grid.rows
                next.getContext('2d')?.putImageData(new ImageData(grid.pixels, grid.columns, grid.rows), 0, 0)
            }
            next.style.opacity = grid ? '1' : '0'
            previous.style.opacity = '0'
            activeLayer = 1 - activeLayer
        }

        const update = (): void => {
            if (document.hidden) {
                return
            }
            const iframe = replayer.iframe
            const recordedDocument = iframe?.contentDocument
            const recording = { width: Number(iframe?.width), height: Number(iframe?.height) }
            const container = replayer.wrapper.ownerDocument.body.getBoundingClientRect()
            const scaled = replayer.wrapper.getBoundingClientRect()
            if (!recordedDocument || !recording.width || !recording.height || !isBoxed(container, scaled)) {
                show(null)
                return
            }
            const sampled = sampler.sample(recordedDocument, recording)
            if (!sampled) {
                show(null)
                return
            }
            const overhang = { x: container.width * OVERHANG, y: container.height * OVERHANG }
            const extended = extendGrid(
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
            show(extended.grid, extended.area)
        }

        update()
        const interval = setInterval(update, SAMPLE_INTERVAL_MS)
        return () => {
            clearInterval(interval)
            layers.forEach((layer) => layer?.style.setProperty('opacity', '0'))
        }
    }, [player, enabled])

    if (!enabled) {
        return null
    }

    return (
        <div className="PlayerFrame__ambient" aria-hidden>
            <canvas ref={firstLayer} className="PlayerFrame__ambient-layer" />
            <canvas ref={secondLayer} className="PlayerFrame__ambient-layer" />
        </div>
    )
}
