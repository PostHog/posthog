export interface Box {
    left: number
    top: number
    width: number
    height: number
}

// ONNX detectors need input dims on a 32-px grid; floor at 32.
