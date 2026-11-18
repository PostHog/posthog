import { mulberry32 } from '../dev/bench-common.ts'
import { dbnetChwTs, qrRgbaTs, safetyChwTs, yunetChwTs } from '../dev/pixel-convert-reference.ts'
import { type PerPlane, rgbToChw, rgbToNormalizedChw, rgbToRgba } from './pixel-convert.ts'

const IMAGENET_MEAN: PerPlane = [0.485, 0.456, 0.406]
const IMAGENET_STD: PerPlane = [0.229, 0.224, 0.225]

type Destination = Float32Array | Uint8ClampedArray

// Methods rather than function properties, so that each entry can narrow `out` to its own array type.
interface Conversion {
    name: string
    valuesPerPixel: number
    bytesPerValue: number
    view(buffer: ArrayBuffer, byteOffset: number, length: number): Destination
    rust(rgb: Uint8Array, out: Destination): void
    ts(rgb: Uint8Array, out: Destination): void
}

const floatPlanes = {
    valuesPerPixel: 3,
    bytesPerValue: 4,
    view: (buffer: ArrayBuffer, byteOffset: number, length: number) => new Float32Array(buffer, byteOffset, length),
}

const CONVERSIONS: Conversion[] = [
    {
        name: 'dbnet',
        ...floatPlanes,
        rust: (rgb, chw: Float32Array) => rgbToNormalizedChw(rgb, chw, 'bgr', IMAGENET_MEAN, IMAGENET_STD),
        ts: (rgb, chw: Float32Array) => dbnetChwTs(rgb, chw, IMAGENET_MEAN, IMAGENET_STD),
    },
    {
        name: 'yunet',
        ...floatPlanes,
        rust: (rgb, chw: Float32Array) => rgbToChw(rgb, chw, 'bgr'),
        ts: (rgb, chw: Float32Array) => yunetChwTs(rgb, chw),
    },
    {
        name: 'safety',
        ...floatPlanes,
        rust: (rgb, chw: Float32Array) => rgbToChw(rgb, chw, 'rgb'),
        ts: (rgb, chw: Float32Array) => safetyChwTs(rgb, chw),
    },
    {
        name: 'qr',
        valuesPerPixel: 4,
        bytesPerValue: 1,
        view: (buffer, byteOffset, length) => new Uint8ClampedArray(buffer, byteOffset, length),
        rust: (rgb, rgba: Uint8ClampedArray) => rgbToRgba(rgb, rgba),
        ts: (rgb, rgba: Uint8ClampedArray) => qrRgbaTs(rgb, rgba),
    },
]

// One pixel, and counts either side of every vector width the kernels can use, so that each scalar
// tail runs.
const SMALL_PIXEL_COUNTS = [1, 2, 3, 5, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127, 129, 255, 257, 1001]
// The sizes production converts: the safety input, two text canvases, the YuNet input, and two
// code-reader frames.
const PRODUCTION_SIZES = [
    [224, 224],
    [640, 384],
    [928, 576],
    [640, 640],
    [638, 359],
    [1181, 664],
]
const PIXEL_COUNTS = [...SMALL_PIXEL_COUNTS, ...PRODUCTION_SIZES.map(([width, height]) => width * height)]

function allocate(conversion: Conversion, pixels: number): Destination {
    const length = conversion.valuesPerPixel * pixels
    return conversion.view(new ArrayBuffer(length * conversion.bytesPerValue), 0, length)
}

function randomRgb(pixels: number, seed: number): Uint8Array {
    const random = mulberry32(seed)
    const words = new Uint32Array(Math.ceil((3 * pixels) / 4))
    for (let i = 0; i < words.length; i++) {
        words[i] = random() * 2 ** 32
    }
    return new Uint8Array(words.buffer, 0, 3 * pixels)
}

// Every channel steps through all 256 values with a different stride, so every entry of every
// plane's lookup table is read at least once.
function everyValueRgb(): Uint8Array {
    const rgb = new Uint8Array(3 * 256)
    for (let p = 0; p < 256; p++) {
        rgb[3 * p] = p
        rgb[3 * p + 1] = (7 * p + 85) % 256
        rgb[3 * p + 2] = (13 * p + 170) % 256
    }
    return rgb
}

function bytesOf(view: ArrayBufferView): Buffer {
    return Buffer.from(view.buffer, view.byteOffset, view.byteLength)
}

// Reports the first byte that differs rather than both arrays, which can hold millions of values.
function firstDifference(
    rust: ArrayBufferView,
    ts: ArrayBufferView
): { byte: number; rust: number; ts: number } | { rustBytes: number; tsBytes: number } | null {
    const [a, b] = [bytesOf(rust), bytesOf(ts)]
    if (a.length !== b.length) {
        return { rustBytes: a.length, tsBytes: b.length }
    }
    if (a.equals(b)) {
        return null
    }
    const byte = a.findIndex((value, index) => value !== b[index])
    return { byte, rust: a[byte], ts: b[byte] }
}

function compare(conversion: Conversion, rgb: Uint8Array): ReturnType<typeof firstDifference> {
    const pixels = rgb.length / 3
    const [rust, ts] = [allocate(conversion, pixels), allocate(conversion, pixels)]
    conversion.rust(rgb, rust)
    conversion.ts(rgb, ts)
    return firstDifference(rust, ts)
}

describe('pixel conversions', () => {
    test.each(CONVERSIONS)('$name matches the TypeScript it replaced, bit for bit', (conversion) => {
        const mismatches = [
            ...PIXEL_COUNTS.map((pixels) => ({ pixels, difference: compare(conversion, randomRgb(pixels, pixels)) })),
            { pixels: 'every value', difference: compare(conversion, everyValueRgb()) },
        ].filter(({ difference }) => difference !== null)

        expect(mismatches).toEqual([])
    })

    test.each([
        { mean: [0, 0, 0], std: [1, 1, 1] },
        { mean: [0.5, 0.5, 0.5], std: [0.5, 0.5, 0.5] },
        { mean: [0.1234567, 0.7654321, 0.3333333], std: [0.0271828, 0.314159, 0.9999999] },
    ] as { mean: PerPlane; std: PerPlane }[])(
        'normalized planes match the TypeScript for mean $mean and std $std',
        ({ mean, std }) => {
            for (const rgb of [randomRgb(1001, 1), everyValueRgb()]) {
                const [rust, ts] = [new Float32Array(rgb.length), new Float32Array(rgb.length)]
                rgbToNormalizedChw(rgb, rust, 'bgr', mean, std)
                dbnetChwTs(rgb, ts, mean, std)

                expect(firstDifference(rust, ts)).toBeNull()
            }
        }
    )

    test.each(CONVERSIONS)('$name reads and writes only inside the views it is given', (conversion) => {
        const pixels = 37
        const source = new Uint8Array(5 + 3 * pixels + 5)
        source.set(randomRgb(pixels, 3), 5)
        const rgb = source.subarray(5, 5 + 3 * pixels)
        const guardBytes = 16
        const length = conversion.valuesPerPixel * pixels
        const buffer = new ArrayBuffer(guardBytes + length * conversion.bytesPerValue + guardBytes)
        const whole = new Uint8Array(buffer).fill(0xa5)
        const out = conversion.view(buffer, guardBytes, length)
        const expected = allocate(conversion, pixels)

        conversion.rust(rgb, out)
        conversion.ts(rgb, expected)

        expect(firstDifference(out, expected)).toBeNull()
        expect([...whole.subarray(0, guardBytes), ...whole.subarray(guardBytes + out.byteLength)]).toEqual(
            Array.from({ length: 2 * guardBytes }, () => 0xa5)
        )
    })

    test.each(CONVERSIONS)('$name refuses a layout that does not fit', (conversion) => {
        const rgb = randomRgb(10, 5)

        expect(() => conversion.rust(rgb, allocate(conversion, 10).subarray(1))).toThrow(
            `destination length is ${conversion.valuesPerPixel * 10 - 1}, expected ${conversion.valuesPerPixel * 10}`
        )
        expect(() => conversion.rust(rgb.subarray(1), allocate(conversion, 10))).toThrow(
            'rgb length 29 is not a whole number of pixels'
        )
    })

    test('refuses a destination that shares memory with its source', () => {
        const buffer = new ArrayBuffer(64)

        expect(() => rgbToRgba(new Uint8Array(buffer, 0, 30), new Uint8ClampedArray(buffer, 20, 40))).toThrow(
            'the source and destination share memory'
        )
    })
})
