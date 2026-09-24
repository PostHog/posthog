export interface TerminalWorkerBoot {
    wasmUrl: string
    bios: ArrayBuffer
    vgaBios: ArrayBuffer
    kernel: ArrayBuffer
    canvas: OffscreenCanvas
}

export type TerminalWorkerRequest =
    | ({ type: 'start' } & TerminalWorkerBoot)
    | { type: 'run' }
    | { type: 'serial'; port: number; bytes: Uint8Array }
    | { type: 'keyboard'; codes: number[] }
    | { type: 'mouse'; event: 'mouse-click' | 'mouse-delta'; value: boolean[] | number[] }
    | { type: 'display'; visible: boolean }
    | { type: '9p'; id: number; bytes: Uint8Array }

export type TerminalWorkerResponse =
    | { type: 'loaded' }
    | { type: 'serial'; port: number; bytes: Uint8Array }
    | { type: '9p'; id: number; bytes: Uint8Array }
    | { type: 'error'; message: string }
