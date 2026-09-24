import { V86 } from 'v86'

import type { TerminalWorkerRequest, TerminalWorkerResponse } from './terminalWorkerProtocol'

interface FramebufferLayer {
    image_data: ImageData
    screen_x: number
    screen_y: number
    buffer_x: number
    buffer_y: number
    buffer_width: number
    buffer_height: number
}

// v86's DOM-free adapter and PS/2 bus are not declared in its public types.
type WorkerV86 = V86 & {
    bus: { send: (event: string, value: boolean[] | number[]) => void }
    screen_adapter: {
        set_size_graphical: (width: number, height: number) => void
        update_buffer: (layers: FramebufferLayer[]) => void
        clear_screen: () => void
    }
    v86: { cpu: { devices: { vga: { screen_fill_buffer: () => void } } } }
}

function send(message: TerminalWorkerResponse, transfer: Transferable[] = []): void {
    postMessage(message, { transfer })
}

let emulator: WorkerV86 | undefined
let visible = false
let nextRequest = 0
const replies = new Map<number, { tag: number; reply: (bytes: Uint8Array) => void }>()
const serial = [new Uint8Array(8192), new Uint8Array(8192)]
const lengths = [0, 0]
let flushScheduled = false

function flushSerial(): void {
    for (const port of [0, 1]) {
        if (lengths[port]) {
            const bytes = serial[port].slice(0, lengths[port])
            lengths[port] = 0
            send({ type: 'serial', port, bytes }, [bytes.buffer])
        }
    }
}

function output(port: number, byte: number): void {
    serial[port][lengths[port]++] = byte
    if (lengths[port] === serial[port].length) {
        flushSerial()
    }
    if (!flushScheduled) {
        flushScheduled = true
        queueMicrotask(() => {
            flushScheduled = false
            flushSerial()
        })
    }
}

function receive(message: TerminalWorkerRequest): void {
    switch (message.type) {
        case 'start': {
            if (emulator) {
                return
            }
            const { canvas } = message
            const context = canvas.getContext('2d', { alpha: false })
            if (!context) {
                throw new Error('Terminal display could not start.')
            }
            emulator = new V86({
                wasm_path: message.wasmUrl,
                bios: { buffer: message.bios },
                vga_bios: { buffer: message.vgaBios },
                bzimage: { buffer: message.kernel },
                memory_size: 512 * 1024 * 1024,
                filesystem: {
                    handle9p: (request, reply) => {
                        const id = nextRequest++
                        const tag = request[5] | (request[6] << 8)
                        if (request[4] === 108) {
                            // Flushed 9P requests do not receive a reply from the filesystem server.
                            const oldTag = request[7] | (request[8] << 8)
                            for (const [pendingId, pending] of replies) {
                                if (pending.tag === oldTag) {
                                    replies.delete(pendingId)
                                }
                            }
                        }
                        replies.set(id, { tag, reply })
                        // Guest memory belongs to WASM and cannot be transferred.
                        const bytes = request.slice()
                        send({ type: '9p', id, bytes }, [bytes.buffer])
                    },
                },
                cmdline: 'tsc=reliable mitigations=off random.trust_cpu=on video=640x480',
                vga_memory_size: 8 * 1024 * 1024,
                disable_keyboard: true,
                disable_mouse: true,
                disable_speaker: true,
                uart1: true,
                autostart: false,
            }) as WorkerV86
            const vm = emulator
            vm.add_listener('serial0-output-byte', (byte: number) => output(0, byte))
            vm.add_listener('serial1-output-byte', (byte: number) => output(1, byte))
            vm.add_listener('emulator-loaded', () => {
                // Linux uses a graphical framebuffer; retain v86's headless VGA text adapter for boot.
                Object.assign(vm.screen_adapter, {
                    set_size_graphical: (width: number, height: number): void => {
                        canvas.width = width
                        canvas.height = height
                    },
                    clear_screen: (): void => context.clearRect(0, 0, canvas.width, canvas.height),
                    update_buffer: (layers: FramebufferLayer[]): void => {
                        for (const layer of layers) {
                            context.putImageData(
                                layer.image_data,
                                layer.screen_x - layer.buffer_x,
                                layer.screen_y - layer.buffer_y,
                                layer.buffer_x,
                                layer.buffer_y,
                                layer.buffer_width,
                                layer.buffer_height
                            )
                        }
                    },
                })
                const draw = (): void => {
                    if (visible) {
                        vm.v86.cpu.devices.vga.screen_fill_buffer()
                    }
                    requestAnimationFrame(draw)
                }
                requestAnimationFrame(draw)
                send({ type: 'loaded' })
            })
            break
        }
        case 'run':
            emulator?.run()
            break
        case 'serial':
            emulator?.serial_send_bytes(message.port, message.bytes)
            break
        case 'keyboard':
            emulator?.keyboard_send_scancodes(message.codes)
            break
        case 'mouse':
            emulator?.bus.send(message.event, message.value)
            break
        case 'display':
            visible = message.visible
            break
        case '9p': {
            const reply = replies.get(message.id)
            replies.delete(message.id)
            reply?.reply(message.bytes)
            break
        }
    }
}

self.onmessage = (event: MessageEvent<TerminalWorkerRequest>): void => {
    try {
        receive(event.data)
    } catch {
        send({ type: 'error', message: 'Terminal worker stopped unexpectedly. Restart the terminal.' })
    }
}
self.addEventListener('unhandledrejection', () => {
    send({ type: 'error', message: 'Terminal worker could not start. Restart the terminal.' })
})
