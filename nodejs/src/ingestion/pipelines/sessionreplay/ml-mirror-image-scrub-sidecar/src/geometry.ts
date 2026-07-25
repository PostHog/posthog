export interface Box {
    left: number
    top: number
    width: number
    height: number
}

// ONNX detectors need input dims on a 32-px grid; floor at 32.
/** The largest multiple of 32 that does not exceed n, for a model whose encoder strides by 32.
 *
 *  Floors rather than rounds: rounding to nearest resamples the frame UP by as much as 16px per axis
 *  to reach the next multiple, which adds no information, costs a resample, and softens the very
 *  glyph edges the detector scores. A 894x503 frame became 896x512 that way. */
export function floorTo32(n: number): number {
    return Math.max(32, Math.floor(n / 32) * 32)
}

/** The smallest multiple of 32 that is at least n. Used to PAD a model input up to the stride, never
 *  to resize up to it: padding adds background, where resizing up would resample real pixels. */
export function ceilTo32(n: number): number {
    return Math.max(32, Math.ceil(n / 32) * 32)
}
