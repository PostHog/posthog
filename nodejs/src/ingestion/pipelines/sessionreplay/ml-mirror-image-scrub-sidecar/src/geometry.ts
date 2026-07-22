export interface Box {
    left: number
    top: number
    width: number
    height: number
}

// ONNX detectors need input dims on a 32-px grid; floor at 32.
export function roundTo32(n: number): number {
    return Math.max(32, Math.round(n / 32) * 32)
}
