import assetHashes from './assets/hashes.json'
import { NinePServer } from './ninepServer'
import { TerminalFilesystem } from './terminalFilesystem'
import { TerminalRuntime } from './terminalRuntime'
import { TerminalWorkerClient } from './TerminalWorkerClient'

jest.mock('./TerminalWorkerClient', () => ({ TerminalWorkerClient: jest.fn() }))
jest.mock('v86/build/v86.wasm?url', () => 'wasm', { virtual: true })
jest.mock('./assets/seabios.bin?url', () => 'bios', { virtual: true })
jest.mock('./assets/vgabios.bin?url', () => 'vga', { virtual: true })
jest.mock('./assets/buildroot-bzimage.bin?url', () => 'kernel', { virtual: true })
jest.mock('./assets/jq-linux-i386.bin?url', () => 'jq', { virtual: true })
jest.mock('./assets/tools-linux-i386.tar.gz.bin?url', () => 'tools', { virtual: true })

describe('terminal VM lifecycle', () => {
    const originalGlobals = {
        fetch: globalThis.fetch,
        Blob: globalThis.Blob,
        Response: globalThis.Response,
        DecompressionStream: globalThis.DecompressionStream,
    }
    const originalSubtle = Object.getOwnPropertyDescriptor(crypto, 'subtle')

    beforeEach(() => {
        jest.clearAllMocks()
        HTMLCanvasElement.prototype.transferControlToOffscreen = jest.fn()
        const hashes = [
            '73e3f359102e3a9982c35fce98eb7cd08f18303ac7f1ba6ebfbe6cdc1c244d98',
            'a4bc0d80cc3ca028c73dafa8fee396b8d054ce87ebd8abfbd31b06b437607880',
            '33ca60bd4832f0cf202845fa7ac1a60776c0215e8a20d21a3f07d3722f99e415',
            'ba996e8ce436973e2f39e2639405a37e8c81ba8c722b71c83996278ad0af16dd',
            assetHashes.toolsSha256,
        ]
        Object.defineProperty(crypto, 'subtle', {
            configurable: true,
            value: {
                digest: jest.fn(
                    async () => Uint8Array.from(hashes.shift()!.match(/../g)!, (hex) => parseInt(hex, 16)).buffer
                ),
            },
        })
        Object.assign(globalThis, {
            fetch: jest.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(0) })),
            Blob: jest.fn(() => ({ stream: () => ({ pipeThrough: () => ({}) }) })),
            Response: jest.fn(() => ({ arrayBuffer: async () => new ArrayBuffer(0) })),
            DecompressionStream: jest.fn(),
        })
    })

    afterEach(() => {
        Object.assign(globalThis, originalGlobals)
        if (originalSubtle) {
            Object.defineProperty(crypto, 'subtle', originalSubtle)
        } else {
            Reflect.deleteProperty(crypto, 'subtle')
        }
    })

    it('changes folders only at an empty prompt and quotes folder names', async () => {
        const listeners = new Map<string, (value?: number) => void>()
        const emulator = {
            add_listener: jest.fn((event, callback) => listeners.set(event, callback)),
            loaded: Promise.resolve(),
            send: jest.fn(),
            dispose: jest.fn(),
            serial0_send: jest.fn(),
            serial_send_bytes: jest.fn(),
        }
        jest.mocked(TerminalWorkerClient).mockImplementation(() => emulator as unknown as TerminalWorkerClient)
        const runtime = new TerminalRuntime(jest.fn())
        await runtime.start(
            new NinePServer(new TerminalFilesystem(), jest.fn()),
            new AbortController().signal,
            jest.fn()
        )
        const output = (text: string): void => {
            for (const byte of new TextEncoder().encode(text)) {
                listeners.get('serial0-output-byte')!(byte)
            }
        }
        output('~% ')
        listeners.get('serial1-output-byte')!(30)
        expect(runtime.changeDirectory('/posthog/files/Research')).toBe(true)
        output('\x1b]133;B\x07')
        expect(new TextDecoder().decode(emulator.serial_send_bytes.mock.calls.at(-1)![1])).toBe(
            "cd -- '/posthog/files/Research'\n"
        )
        output('\x1b]133;B\x07')
        expect(runtime.changeDirectory("/posthog/files/A's notes")).toBe(true)
        expect(new TextDecoder().decode(emulator.serial_send_bytes.mock.calls.at(-1)![1])).toBe(
            "cd -- '/posthog/files/A'\\''s notes'\n"
        )
        expect(runtime.changeDirectory('/posthog/files/Other')).toBe(false)
        output('\x1b]133;B\x07')
        runtime.write('nano ')
        expect(runtime.changeDirectory('/posthog/files/Other')).toBe(false)
        runtime.write('report.sql\n')
        output('Editor output')
        expect(runtime.changeDirectory('/posthog/files/Other')).toBe(false)
    })

    it.each(['initializing', 'loaded'])(
        'stops a VM that is %s without allowing late output or startup',
        async (phase) => {
            const listeners = new Map<string, (value?: number) => void>()
            let loaded!: () => void
            const emulator = {
                loaded: new Promise<void>((resolve) => {
                    loaded = resolve
                }),
                add_listener: jest.fn((event, callback) => listeners.set(event, callback)),
                send: jest.fn(),
                dispose: jest.fn(),
            }
            let created!: () => void
            const initialized = new Promise<void>((resolve) => {
                created = resolve
            })
            jest.mocked(TerminalWorkerClient).mockImplementation(() => {
                created()
                return emulator as unknown as TerminalWorkerClient
            })
            const output = jest.fn()
            const ready = jest.fn()
            const display = jest.fn()
            const runtime = new TerminalRuntime(output, display)
            const started = runtime.start(
                new NinePServer(new TerminalFilesystem(), jest.fn()),
                new AbortController().signal,
                ready
            )
            if (phase === 'loaded') {
                loaded()
                await started
                expect(emulator.send).toHaveBeenCalledWith({ type: 'run' })
            } else {
                await initialized
            }
            runtime.dispose()
            loaded()
            await started
            if (phase === 'initializing') {
                expect(emulator.send).not.toHaveBeenCalledWith({ type: 'run' })
            }
            listeners.get('serial0-output-byte')!(65)
            listeners.get('serial1-output-byte')!(30)
            listeners.get('serial1-output-byte')!(17)
            expect(display).not.toHaveBeenCalled()
            expect(emulator.dispose).toHaveBeenCalledTimes(1)
            expect(runtime.read()).toBe('')
            expect(output).not.toHaveBeenCalled()
            expect(ready).not.toHaveBeenCalled()
        }
    )
})
