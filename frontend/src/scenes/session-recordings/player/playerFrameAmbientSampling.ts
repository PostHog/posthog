import { PlayerFrameDimensions } from 'scenes/session-recordings/player/playerFrameScaling'

const MIN_BAR_PX = 8
const GRID_COLUMNS = 8
const MIN_GRID_ROWS = 4
const MAX_GRID_ROWS = 16
const MIN_OPAQUE_ALPHA = 0.5
// Inset from the recording's edge, so a 1px border on the recorded page does not decide the color.
const EDGE_INSET_PX = 3
const MAX_EXTENDED_CELLS = 256
const THUMBNAIL_WIDTH = 16
const THUMBNAIL_HEIGHT = 32

export interface AmbientGrid {
    columns: number
    rows: number
    pixels: Uint8ClampedArray<ArrayBuffer>
}

type Rgba = [number, number, number, number]

interface Thumbnail {
    source: string
    pixels: Uint8ClampedArray<ArrayBuffer>
}

export function isBoxed(container: PlayerFrameDimensions, recording: PlayerFrameDimensions): boolean {
    return Math.max(container.width - recording.width, container.height - recording.height) >= MIN_BAR_PX * 2
}

export function gridSize(recording: PlayerFrameDimensions): { columns: number; rows: number } {
    const rows = Math.round((GRID_COLUMNS * recording.height) / recording.width)
    return { columns: GRID_COLUMNS, rows: Math.min(Math.max(rows, MIN_GRID_ROWS), MAX_GRID_ROWS) }
}

export function parseCssColor(value: string): Rgba | null {
    const match = value.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/)
    if (!match) {
        return null
    }
    const alpha = match[4] === undefined ? 1 : match[4].endsWith('%') ? parseFloat(match[4]) / 100 : Number(match[4])
    return [Number(match[1]), Number(match[2]), Number(match[3]), alpha]
}

// A live DOM cannot be redrawn blurred like a video frame, so a coarse grid of sampled colors stands in for it.
export class AmbientFrameSampler {
    private thumbnails = new WeakMap<HTMLImageElement | HTMLCanvasElement, Thumbnail>()
    private scratch: HTMLCanvasElement | null = null
    private backgroundImages = new Map<string, Rgba | null | 'loading'>()

    sample(doc: Document, recording: PlayerFrameDimensions): AmbientGrid | null {
        const { columns, rows } = gridSize(recording)
        const fallback = this.documentColor(doc)
        const pixels = new Uint8ClampedArray(columns * rows * 4)
        let found = 0
        for (let row = 0; row < rows; row++) {
            for (let column = 0; column < columns; column++) {
                const x = edgeAligned(column, columns, recording.width)
                const y = edgeAligned(row, rows, recording.height)
                const color = this.colorAt(doc, x, y) ?? fallback
                if (color) {
                    found++
                }
                pixels.set(color ?? [0, 0, 0, 0], (row * columns + column) * 4)
            }
        }
        return found ? { columns, rows, pixels } : null
    }

    // Checks every stacked element, because a transparent overlay hides the painted element below from its ancestors.
    private colorAt(doc: Document, x: number, y: number): Rgba | null {
        const view = doc.defaultView
        if (!view) {
            return null
        }
        for (const element of doc.elementsFromPoint(x, y)) {
            if (element instanceof view.HTMLImageElement || element instanceof view.HTMLCanvasElement) {
                const pixel = this.pixelAt(element, x, y)
                if (pixel) {
                    return pixel
                }
            }
            const style = view.getComputedStyle(element)
            const color =
                this.backgroundImageColor(style.backgroundImage, doc.baseURI) ??
                opaque(parseCssColor(style.backgroundColor))
            if (color) {
                return color
            }
        }
        return null
    }

    // Background images are often repeating patterns, so their average color stands in for any point.
    private backgroundImageColor(backgroundImage: string, baseUrl: string): Rgba | null {
        if (!backgroundImage || backgroundImage === 'none') {
            return null
        }
        const url = backgroundImage.match(/url\(["']?([^"')]+)["']?\)/)?.[1]
        if (url) {
            // A relative URL against the replay frame's about:blank base cannot resolve.
            return URL.canParse(url, baseUrl) ? this.imageAverage(new URL(url, baseUrl).href) : null
        }
        return averageColor(
            [...backgroundImage.matchAll(/rgba?\([^)]*\)/g)].map((match) => opaque(parseCssColor(match[0])))
        )
    }

    private imageAverage(url: string): Rgba | null {
        const cached = this.backgroundImages.get(url)
        if (cached !== undefined) {
            return cached === 'loading' ? null : cached
        }
        this.backgroundImages.set(url, 'loading')
        const image = new Image()
        image.crossOrigin = 'anonymous'
        image.onload = () => {
            const thumbnail = this.thumbnail(image)
            this.backgroundImages.set(
                url,
                thumbnail ? averageColor(chunkPixels(thumbnail.pixels).map((pixel) => opaque(pixel))) : null
            )
        }
        image.onerror = () => this.backgroundImages.set(url, null)
        image.src = url
        return null
    }

    private documentColor(doc: Document): Rgba | null {
        const view = doc.defaultView
        for (const element of [doc.body, doc.documentElement]) {
            const color = element && view ? opaque(parseCssColor(view.getComputedStyle(element).backgroundColor)) : null
            if (color) {
                return color
            }
        }
        return null
    }

    private pixelAt(element: HTMLImageElement | HTMLCanvasElement, x: number, y: number): Rgba | null {
        const rect = element.getBoundingClientRect()
        if (rect.width === 0 || rect.height === 0) {
            return null
        }
        const thumbnail = this.thumbnail(element)
        if (!thumbnail) {
            return null
        }
        const column = clamp(Math.floor(((x - rect.left) / rect.width) * THUMBNAIL_WIDTH), 0, THUMBNAIL_WIDTH - 1)
        const row = clamp(Math.floor(((y - rect.top) / rect.height) * THUMBNAIL_HEIGHT), 0, THUMBNAIL_HEIGHT - 1)
        const offset = (row * THUMBNAIL_WIDTH + column) * 4
        const [r, g, b, a] = thumbnail.pixels.slice(offset, offset + 4)
        return opaque([r, g, b, a / 255])
    }

    // Drawn once per image source at a tiny size, so downscaling averages the pixels for free.
    private thumbnail(element: HTMLImageElement | HTMLCanvasElement): Thumbnail | null {
        const isImage = element.tagName === 'IMG'
        if (isImage && !(element as HTMLImageElement).complete) {
            return null
        }
        // A canvas repaints in place, so only images can reuse a thumbnail.
        const source = isImage ? (element as HTMLImageElement).currentSrc : ''
        const cached = this.thumbnails.get(element)
        if (cached && isImage && cached.source === source) {
            return cached
        }
        this.scratch ??= document.createElement('canvas')
        this.scratch.width = THUMBNAIL_WIDTH
        this.scratch.height = THUMBNAIL_HEIGHT
        const context = this.scratch.getContext('2d', { willReadFrequently: true })
        if (!context) {
            return null
        }
        try {
            context.clearRect(0, 0, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
            context.drawImage(element, 0, 0, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
            const thumbnail = { source, pixels: context.getImageData(0, 0, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT).data }
            this.thumbnails.set(element, thumbnail)
            return thumbnail
        } catch {
            // A cross-origin image taints the canvas, and reading it back throws.
            return null
        }
    }
}

export interface Rect {
    left: number
    top: number
    width: number
    height: number
}

export function extendGrid(grid: AmbientGrid, recording: Rect, area: Rect): { grid: AmbientGrid; area: Rect } {
    const cellWidth = recording.width / grid.columns
    const cellHeight = recording.height / grid.rows
    const columnsBefore = Math.ceil((recording.left - area.left) / cellWidth)
    const rowsBefore = Math.ceil((recording.top - area.top) / cellHeight)
    const columns = Math.min(
        columnsBefore + Math.ceil((area.left + area.width - recording.left) / cellWidth),
        MAX_EXTENDED_CELLS
    )
    const rows = Math.min(
        rowsBefore + Math.ceil((area.top + area.height - recording.top) / cellHeight),
        MAX_EXTENDED_CELLS
    )
    const pixels = new Uint8ClampedArray(columns * rows * 4)
    for (let row = 0; row < rows; row++) {
        const sourceRow = clamp(row - rowsBefore, 0, grid.rows - 1)
        for (let column = 0; column < columns; column++) {
            const sourceColumn = clamp(column - columnsBefore, 0, grid.columns - 1)
            const source = (sourceRow * grid.columns + sourceColumn) * 4
            pixels.set(grid.pixels.subarray(source, source + 4), (row * columns + column) * 4)
        }
    }
    return {
        grid: { columns, rows, pixels },
        area: {
            left: recording.left - columnsBefore * cellWidth,
            top: recording.top - rowsBefore * cellHeight,
            width: columns * cellWidth,
            height: rows * cellHeight,
        },
    }
}

export function sameGrid(a: AmbientGrid | null, b: AmbientGrid | null): boolean {
    if (!a || !b) {
        return a === b
    }
    return a.columns === b.columns && a.rows === b.rows && a.pixels.every((value, index) => value === b.pixels[index])
}

export function averageColor(colors: (Rgba | null)[]): Rgba | null {
    const known = colors.filter((color): color is Rgba => !!color)
    if (!known.length) {
        return null
    }
    const sum = known.reduce(
        (total, color) => [total[0] + color[0], total[1] + color[1], total[2] + color[2]],
        [0, 0, 0]
    )
    return [
        Math.round(sum[0] / known.length),
        Math.round(sum[1] / known.length),
        Math.round(sum[2] / known.length),
        255,
    ]
}

function chunkPixels(pixels: Uint8ClampedArray): Rgba[] {
    const result: Rgba[] = []
    for (let offset = 0; offset < pixels.length; offset += 4) {
        result.push([pixels[offset], pixels[offset + 1], pixels[offset + 2], pixels[offset + 3] / 255])
    }
    return result
}

// A cell-centered grid can land inside a card that stops just short of a colored margin the bars should continue.
export function edgeAligned(index: number, count: number, length: number): number {
    return EDGE_INSET_PX + (index / (count - 1)) * (length - 2 * EDGE_INSET_PX)
}

function opaque(color: Rgba | null): Rgba | null {
    return color && color[3] >= MIN_OPAQUE_ALPHA ? [color[0], color[1], color[2], 255] : null
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(Math.max(value, min), max)
}
