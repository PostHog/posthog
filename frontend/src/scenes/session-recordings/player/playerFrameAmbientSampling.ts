import { clamp } from 'lib/utils/numbers'
import { PlayerFrameDimensions, getPlayerFrameScale } from 'scenes/session-recordings/player/playerFrameScaling'

const MIN_BAR_PX = 8
const GRID_COLUMNS = 8
const MIN_GRID_ROWS = 4
const MAX_GRID_ROWS = 16
const MIN_OPAQUE_ALPHA = 0.5
const EDGE_INSET_PX = 3
const MAX_EXTENDED_CELLS = 256
const THUMBNAIL_WIDTH = 16
const THUMBNAIL_HEIGHT = 32
const MAX_BACKGROUND_IMAGES = 200
const MAX_BACKGROUND_IMAGE_LENGTH = 4096
const FETCHABLE_PROTOCOLS = ['https:', 'http:', 'data:', 'blob:']
const MAX_IMAGE_LOADS_PER_SAMPLE = 4
const MAX_DECODED_PIXELS = 4096 * 4096
const MAX_STACK_DEPTH = 32
const BLEND_TIME_CONSTANT_MS = 1500
const BLEND_SETTLE_DELTA = 2

export type Rgba = [number, number, number, number]

export interface AmbientGrid {
    columns: number
    rows: number
    pixels: Uint8ClampedArray<ArrayBuffer>
}

export interface Rect {
    left: number
    top: number
    width: number
    height: number
}

interface ImageThumbnail {
    source: string
    pixels: Uint8ClampedArray | null
}

export function isBoxed(container: PlayerFrameDimensions, recording: PlayerFrameDimensions): boolean {
    return Math.max(container.width - recording.width, container.height - recording.height) >= MIN_BAR_PX * 2
}

// Matches PlayerFrame's scaling, because the wrapper's measured size lags until its scale applies.
export function scaledFrameRect(container: PlayerFrameDimensions, recording: PlayerFrameDimensions): Rect | null {
    if (!(recording.width >= 1 && recording.height >= 1 && container.width >= 1 && container.height >= 1)) {
        return null
    }
    const { scale } = getPlayerFrameScale(container, recording)
    const width = recording.width * scale
    const height = recording.height * scale
    return { width, height, left: (container.width - width) / 2, top: (container.height - height) / 2 }
}

export function gridSize(recording: PlayerFrameDimensions): { columns: number; rows: number } {
    const rows = Math.round((GRID_COLUMNS * recording.height) / recording.width)
    return { columns: GRID_COLUMNS, rows: clamp(rows, MIN_GRID_ROWS, MAX_GRID_ROWS) }
}

export function parseCssColor(value: string): Rgba | null {
    const match = value.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/)
    if (!match) {
        return null
    }
    const alpha = match[4] === undefined ? 1 : match[4].endsWith('%') ? parseFloat(match[4]) / 100 : Number(match[4])
    return [Number(match[1]), Number(match[2]), Number(match[3]), alpha]
}

export class AmbientFrameSampler {
    private images = new WeakMap<HTMLImageElement, ImageThumbnail>()
    private backgroundImages = new Map<string, Rgba | null>()
    private scratch: HTMLCanvasElement | null = null
    private canvasesThisSample = new Map<HTMLCanvasElement, Uint8ClampedArray | null>()
    private elementColorsThisSample = new Map<Element, Rgba | null>()
    onBackgroundImageLoad: (() => void) | null = null
    // Canvases repaint without a DOM mutation, and the image load cap defers work, so either needs another sample.
    needsResample = false
    private imageLoadsThisSample = 0

    sample(doc: Document, recording: PlayerFrameDimensions): AmbientGrid | null {
        const view = doc.defaultView
        if (!view) {
            return null
        }
        this.needsResample = false
        this.imageLoadsThisSample = 0
        const { columns, rows } = gridSize(recording)
        const fallback = this.documentColor(doc, view)
        const pixels = new Uint8ClampedArray(columns * rows * 4)
        for (let row = 0; row < rows; row++) {
            for (let column = 0; column < columns; column++) {
                const x = edgeAligned(column, columns, recording.width)
                const y = edgeAligned(row, rows, recording.height)
                // A cell with no opaque color stays transparent, so the bars keep the player's own background there.
                const color = this.colorAt(doc, view, x, y) ?? fallback
                if (color) {
                    pixels.set(color, (row * columns + column) * 4)
                }
            }
        }
        this.canvasesThisSample.clear()
        this.elementColorsThisSample.clear()
        return { columns, rows, pixels }
    }

    // Checks every stacked element, because a transparent overlay hides the painted element below from its ancestors.
    private colorAt(doc: Document, view: Window & typeof globalThis, x: number, y: number): Rgba | null {
        for (const element of doc.elementsFromPoint(x, y).slice(0, MAX_STACK_DEPTH)) {
            const pixel =
                element instanceof view.HTMLImageElement
                    ? this.pixelAt(element, this.imagePixels(element), x, y)
                    : element instanceof view.HTMLCanvasElement
                      ? this.pixelAt(element, this.canvasPixels(element), x, y)
                      : null
            const color = pixel ?? this.elementColor(element, view)
            if (color) {
                return color
            }
        }
        return null
    }

    private elementColor(element: Element, view: Window & typeof globalThis): Rgba | null {
        if (!this.elementColorsThisSample.has(element)) {
            const style = view.getComputedStyle(element)
            this.elementColorsThisSample.set(
                element,
                this.backgroundImageColor(style.backgroundImage, view) ?? opaque(parseCssColor(style.backgroundColor))
            )
        }
        return this.elementColorsThisSample.get(element) ?? null
    }

    private documentColor(doc: Document, view: Window): Rgba | null {
        for (const element of [doc.body, doc.documentElement]) {
            const color = element ? opaque(parseCssColor(view.getComputedStyle(element).backgroundColor)) : null
            if (color) {
                return color
            }
        }
        return null
    }

    private backgroundImageColor(backgroundImage: string, view: Window & typeof globalThis): Rgba | null {
        if (!backgroundImage || backgroundImage === 'none') {
            return null
        }
        const cached = this.backgroundImages.get(backgroundImage)
        if (cached !== undefined) {
            return cached
        }
        if (backgroundImage.length > MAX_BACKGROUND_IMAGE_LENGTH) {
            return null
        }
        const hasRoom = this.backgroundImages.size < MAX_BACKGROUND_IMAGES
        const url = backgroundImage.match(/url\(["']?([^"')]+)["']?\)/)?.[1]
        if (!url) {
            const gradient = gradientColor(backgroundImage)
            if (hasRoom) {
                this.backgroundImages.set(backgroundImage, gradient)
            }
            return gradient
        }
        if (!hasRoom) {
            return null
        }
        if (this.imageLoadsThisSample >= MAX_IMAGE_LOADS_PER_SAMPLE) {
            this.needsResample = true
            return null
        }
        this.backgroundImages.set(backgroundImage, null)
        this.loadBackgroundImage(backgroundImage, url, view)
        return null
    }

    private loadBackgroundImage(key: string, url: string, view: Window & typeof globalThis): void {
        // Computed styles resolve recorded URLs to absolute ones, so a relative URL here would only hit the app origin.
        if (!URL.canParse(url) || !FETCHABLE_PROTOCOLS.includes(new URL(url).protocol)) {
            return
        }
        this.imageLoadsThisSample++
        // The recorded document's own policy admits any image, and the app's would report every one.
        const image = new view.Image()
        image.crossOrigin = 'anonymous'
        image.referrerPolicy = 'no-referrer'
        image.onload = () => {
            const pixels = this.draw(image)
            this.backgroundImages.set(key, pixels ? averageColor(rgbaPixels(pixels).map(opaque)) : null)
            this.onBackgroundImageLoad?.()
        }
        image.src = url
    }

    private pixelAt(element: Element, pixels: Uint8ClampedArray | null, x: number, y: number): Rgba | null {
        const rect = element.getBoundingClientRect()
        if (!pixels || rect.width === 0 || rect.height === 0) {
            return null
        }
        const column = clamp(Math.floor(((x - rect.left) / rect.width) * THUMBNAIL_WIDTH), 0, THUMBNAIL_WIDTH - 1)
        const row = clamp(Math.floor(((y - rect.top) / rect.height) * THUMBNAIL_HEIGHT), 0, THUMBNAIL_HEIGHT - 1)
        return opaque(rgbaAt(pixels, (row * THUMBNAIL_WIDTH + column) * 4))
    }

    private imagePixels(image: HTMLImageElement): Uint8ClampedArray | null {
        if (!image.complete) {
            return null
        }
        const cached = this.images.get(image)
        if (cached && cached.source === image.currentSrc) {
            return cached.pixels
        }
        const pixels = this.draw(image)
        this.images.set(image, { source: image.currentSrc, pixels })
        return pixels
    }

    private canvasPixels(canvas: HTMLCanvasElement): Uint8ClampedArray | null {
        this.needsResample = true
        if (!this.canvasesThisSample.has(canvas)) {
            this.canvasesThisSample.set(canvas, this.draw(canvas))
        }
        return this.canvasesThisSample.get(canvas) ?? null
    }

    private draw(source: HTMLImageElement | HTMLCanvasElement): Uint8ClampedArray | null {
        const [width, height] =
            'naturalWidth' in source ? [source.naturalWidth, source.naturalHeight] : [source.width, source.height]
        if (width * height > MAX_DECODED_PIXELS) {
            return null
        }
        this.scratch ??= document.createElement('canvas')
        this.scratch.width = THUMBNAIL_WIDTH
        this.scratch.height = THUMBNAIL_HEIGHT
        const context = this.scratch.getContext('2d', { willReadFrequently: true })
        if (!context) {
            return null
        }
        try {
            context.drawImage(source, 0, 0, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
            return context.getImageData(0, 0, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT).data
        } catch {
            // Browsers differ on whether resizing clears a cross-origin taint, so start from a fresh canvas.
            this.scratch = null
            return null
        }
    }
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
            const source = (sourceRow * grid.columns + clamp(column - columnsBefore, 0, grid.columns - 1)) * 4
            const target = (row * columns + column) * 4
            for (let channel = 0; channel < 4; channel++) {
                pixels[target + channel] = grid.pixels[source + channel]
            }
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

export class AmbientBlend {
    private current = new Float32Array(0)
    private target = new Uint8ClampedArray(0)
    private lastStepTime: number | null = null
    private image: ImageData | null = null
    columns = 0
    rows = 0
    pixels = new Uint8ClampedArray(0)

    setTarget(grid: AmbientGrid): boolean {
        this.target = grid.pixels
        this.lastStepTime = null
        if (grid.columns === this.columns && grid.rows === this.rows && this.current.length) {
            return false
        }
        this.columns = grid.columns
        this.rows = grid.rows
        this.current = Float32Array.from(grid.pixels)
        this.pixels = new Uint8ClampedArray(grid.pixels)
        return true
    }

    snap(): void {
        this.current = Float32Array.from(this.target)
        this.pixels.set(this.target)
    }

    step(now: number): { changed: boolean; settled: boolean } {
        const elapsed = this.lastStepTime === null ? 0 : now - this.lastStepTime
        this.lastStepTime = now
        const fraction = 1 - Math.exp(-Math.max(elapsed, 0) / BLEND_TIME_CONSTANT_MS)
        let changed = false
        let settled = true
        for (let index = 0; index < this.current.length; index++) {
            const next = this.current[index] + (this.target[index] - this.current[index]) * fraction
            const done = Math.abs(this.target[index] - next) < BLEND_SETTLE_DELTA
            this.current[index] = done ? this.target[index] : next
            settled &&= done
            const byte = Math.round(this.current[index])
            if (this.pixels[index] !== byte) {
                this.pixels[index] = byte
                changed = true
            }
        }
        return { changed, settled }
    }

    imageData(): ImageData {
        if (this.image?.data !== this.pixels) {
            this.image = new ImageData(this.pixels as Uint8ClampedArray<ArrayBuffer>, this.columns, this.rows)
        }
        return this.image
    }
}

function gradientColor(backgroundImage: string): Rgba | null {
    return averageColor(
        [...backgroundImage.matchAll(/rgba?\([^)]*\)/g)].map((match) => opaque(parseCssColor(match[0])))
    )
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

export function edgeAligned(index: number, count: number, length: number): number {
    return EDGE_INSET_PX + (index / (count - 1)) * (length - 2 * EDGE_INSET_PX)
}

function rgbaAt(pixels: Uint8ClampedArray, offset: number): Rgba {
    return [pixels[offset], pixels[offset + 1], pixels[offset + 2], pixels[offset + 3] / 255]
}

function rgbaPixels(pixels: Uint8ClampedArray): Rgba[] {
    return Array.from({ length: pixels.length / 4 }, (_, index) => rgbaAt(pixels, index * 4))
}

function opaque(color: Rgba | null): Rgba | null {
    return color && color[3] >= MIN_OPAQUE_ALPHA ? [color[0], color[1], color[2], 255] : null
}
