import type { V86 } from 'v86'
import wasmUrl from 'v86/build/v86.wasm?url'

import kernelUrl from './assets/buildroot-bzimage.bin?url'
import assetHashes from './assets/hashes.json'
import jqUrl from './assets/jq-linux-i386.bin?url'
import biosUrl from './assets/seabios.bin?url'
import toolsUrl from './assets/tools-linux-i386.tar.gz.bin?url'
import vgaBiosUrl from './assets/vgabios.bin?url'
import { NinePServer } from './ninepServer'
import packageManifest from './terminal-packages.json'
import { DISPLAY_SCRIPT, TerminalDisplayInput } from './terminalDisplay'
import { TerminalPackages } from './terminalPackages'

function browserClock(): { timestamp: number; timezone: string } {
    const now = new Date()
    const offset = now.getTimezoneOffset()
    const hours = Math.floor(Math.abs(offset) / 60)
    const minutes = String(Math.abs(offset) % 60).padStart(2, '0')
    // POSIX timezone offsets have the opposite sign to the displayed UTC offset.
    const label = `${offset > 0 ? '-' : '+'}${String(hours).padStart(2, '0')}${minutes}`
    return {
        timestamp: Math.floor(now.getTime() / 1000),
        timezone: offset === 0 ? 'UTC0' : `<${label}>${offset > 0 ? '' : '-'}${hours}:${minutes}`,
    }
}

async function verifiedImage(url: string, sha256: string, signal: AbortSignal): Promise<ArrayBuffer> {
    const response = await fetch(url, {
        signal,
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
    })
    if (!response.ok) {
        throw new Error(`Terminal download failed (${response.status}). Retry starting the terminal.`)
    }
    const buffer = await response.arrayBuffer()
    const digest = await crypto.subtle.digest('SHA-256', buffer)
    const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
    if (actual !== sha256) {
        throw new Error('Terminal download verification failed. Reload PostHog before trying again.')
    }
    return buffer
}

export class TerminalRuntime {
    private emulator?: V86
    private emulatorLoaded = false
    private output = ''
    private decoder = new TextDecoder()
    private outputBuffer = new Uint8Array(8192)
    private outputLength = 0
    private outputScheduled = false
    private ready = false
    private disposed = false
    private columns = 80
    private rows = 24
    private promptTail = ''
    private atPrompt = false
    private hasPrompt = false
    private pendingDirectory?: string

    readonly screen = document.createElement('div')
    readonly displayInput = new TerminalDisplayInput(
        (codes) => this.emulator?.keyboard_send_scancodes(codes),
        (buttons) => this.sendMouse('mouse-click', buttons)
    )

    constructor(
        private onOutput: (bytes: Uint8Array) => void,
        private onDisplay: (active: boolean) => void = () => {}
    ) {
        this.screen.append(document.createElement('div'), document.createElement('canvas'))
    }

    // v86 exposes PS/2 mouse input on its bus but has no public send-mouse method.
    private sendMouse(event: 'mouse-click' | 'mouse-delta', value: boolean[] | number[]): void {
        const emulator = this.emulator as
            | (V86 & { bus: { send: (event: string, value: boolean[] | number[]) => void } })
            | undefined
        emulator?.bus.send(event, value)
    }

    moveMouse(x: number, y: number): void {
        this.sendMouse('mouse-delta', [x, -y])
    }

    attachDisplay(container: HTMLElement): void {
        container.append(this.screen)
    }

    detachDisplay(): void {
        this.displayInput.release()
        this.screen.remove()
    }

    async start(
        server: NinePServer,
        signal: AbortSignal,
        onReady: () => void,
        folder = '/posthog/files'
    ): Promise<void> {
        const { V86 } = await import('v86')
        if (signal.aborted || this.disposed) {
            return
        }
        const [bios, vgaBios, kernel, jq, tools] = await Promise.all([
            verifiedImage(biosUrl, '73e3f359102e3a9982c35fce98eb7cd08f18303ac7f1ba6ebfbe6cdc1c244d98', signal),
            verifiedImage(vgaBiosUrl, 'a4bc0d80cc3ca028c73dafa8fee396b8d054ce87ebd8abfbd31b06b437607880', signal),
            verifiedImage(
                // This image's uncached 9P reads work before API file sizes are known; Linux 6.8 clamps them to zero.
                kernelUrl,
                packageManifest.kernel.sha256,
                signal
            ),
            verifiedImage(jqUrl, 'ba996e8ce436973e2f39e2639405a37e8c81ba8c722b71c83996278ad0af16dd', signal),
            verifiedImage(toolsUrl, assetHashes.toolsSha256, signal),
        ])
        if (signal.aborted || this.disposed) {
            return
        }
        // The guest's BusyBox tar has no gzip support.
        const toolsArchive = await new Response(
            new Blob([tools]).stream().pipeThrough(new DecompressionStream('gzip'))
        ).arrayBuffer()
        if (signal.aborted || this.disposed) {
            return
        }
        new TerminalPackages(server.filesystem, signal).mount()
        const bin = server.filesystem.directory('bin', server.filesystem.root)
        server.filesystem.text('display', bin, DISPLAY_SCRIPT)
        server.filesystem.file('jq', bin, async () => ({ bytes: new Uint8Array(jq) })).size = jq.byteLength
        server.filesystem.file('tools.tar', bin, async () => ({ bytes: new Uint8Array(toolsArchive) })).size =
            toolsArchive.byteLength
        const emulator = (this.emulator = new V86({
            wasm_path: wasmUrl,
            bios: { buffer: bios },
            vga_bios: { buffer: vgaBios },
            bzimage: { buffer: kernel },
            memory_size: 512 * 1024 * 1024,
            filesystem: { handle9p: server.handle },
            cmdline: 'tsc=reliable mitigations=off random.trust_cpu=on video=640x480',
            vga_memory_size: 8 * 1024 * 1024,
            screen: { container: this.screen, use_graphical_text: true },
            disable_keyboard: true,
            disable_mouse: true,
            disable_speaker: true,
            uart1: true,
            autostart: false,
        }))
        emulator.add_listener('emulator-loaded', () => {
            this.emulatorLoaded = true
            if (this.disposed || signal.aborted) {
                void emulator.destroy()
            } else {
                emulator.run()
            }
        })
        let boot = ''
        let configured = false
        emulator.add_listener('serial1-output-byte', (byte: number) => {
            if (this.disposed) {
                return
            }
            if (this.ready && (byte === 17 || byte === 18)) {
                this.onDisplay(byte === 17)
            }
            if (configured && !this.ready && byte === 30) {
                this.ready = true
                this.resize(this.columns, this.rows)
                onReady()
            }
        })
        emulator.add_listener('serial0-output-byte', (byte: number) => {
            if (this.disposed) {
                return
            }
            this.atPrompt = false
            this.promptTail = (this.promptTail + String.fromCharCode(byte)).slice(-8)
            if (this.promptTail.endsWith('\x1b]133;B\x07')) {
                this.hasPrompt = true
                this.atPrompt = true
                if (this.pendingDirectory) {
                    const folder = this.pendingDirectory
                    this.pendingDirectory = undefined
                    this.changeDirectory(folder)
                }
            }
            this.outputBuffer[this.outputLength++] = byte
            if (this.outputLength === this.outputBuffer.length) {
                this.flushOutput()
            }
            if (!this.outputScheduled) {
                this.outputScheduled = true
                queueMicrotask(() => {
                    this.outputScheduled = false
                    this.flushOutput()
                })
            }
            if (configured) {
                return
            }
            boot = (boot + String.fromCharCode(byte)).slice(-4096)
            if (!configured && boot.endsWith('~% ')) {
                configured = true
                const clock = browserClock()
                const setup = new TextEncoder().encode(
                    [
                        `stty rows ${this.rows} cols ${this.columns}`,
                        'export TERM=xterm-256color',
                        'unset TZ',
                        `printf '%s\\n' '${clock.timezone}' > /etc/TZ`,
                        `date -s @${clock.timestamp} > /dev/null`,
                        'tar -xf /posthog/bin/tools.tar -C / || exit',
                        'export EDITOR=nano VISUAL=nano',
                        'mkdir -p /opt/posthog-packages && mount -t tmpfs -o size=256m tmpfs /opt/posthog-packages || exit',
                        'ln -sf /opt/posthog-tools/lib/ld-musl-i386.so.1 /lib/ld-musl-i386.so.1',
                        'cp /posthog/bin/jq /usr/bin/jq && chmod +x /usr/bin/jq || exit',
                        'cp /posthog/bin/ph /usr/bin/ph && chmod +x /usr/bin/ph || exit',
                        'cp /posthog/bin/run /usr/bin/run && chmod +x /usr/bin/run || exit',
                        '[ -e /dev/fd ] || ln -s /proc/self/fd /dev/fd',
                        'mkdir -p /usr/local/bin && cp /posthog/bin/rm /usr/local/bin/rm && chmod +x /usr/local/bin/rm || exit',
                        'export PATH=/usr/local/bin:$PATH',
                        'cp /posthog/bin/open /usr/bin/open && chmod +x /usr/bin/open || exit',
                        'cp /posthog/bin/display /usr/bin/display && chmod +x /usr/bin/display || exit',
                        ...Object.values(packageManifest.packages).flatMap((pkg) =>
                            Object.keys(pkg.commands).map(
                                (command) =>
                                    `cp /posthog/bin/${command} /usr/bin/${command} && chmod +x /usr/bin/${command} || exit`
                            )
                        ),
                        'stty -F /dev/ttyS1 raw -echo',
                        // Detach the control helper so the shell's wait command only waits for user jobs.
                        '(while read -r command first second; do case "$command" in resize) stty -F /dev/ttyS0 rows "$first" cols "$second";; clock) date -s "@$first" > /dev/null; printf "%s\\n" "$second" > /etc/TZ;; esac; done < /dev/ttyS1 &)',
                        "alias ls='ls --color=auto'",
                        "export PS1='\\[\\033[32m\\]posthog\\[\\033[0m\\]:\\[\\033[34m\\]\\w\\[\\033[0m\\] $ \\[\\e]133;B\\a\\]'",
                        `cd -- '${folder.replaceAll("'", "'\\''")}' || cd /posthog/files`,
                        'clear',
                        "printf 'PostHog terminal\\n\\nTry:\\n  mc\\n  tree -C -L 3\\n  nano Unfiled/Notebooks/Foobar.md\\n  vi Unfiled/Notebooks/Foobar.md\\n  ncdu -r /posthog/files\\n  mkdir Research\\n  ph tools\\n  ph notebooks-list --limit 10 | jq .\\n  cat /posthog/README.txt\\n\\nUse your own notebook path. In nano, Ctrl+S saves and Ctrl+X exits.\\nIn vi, save with :wq; quit with :q!. Selecting text copies it.\\nFolder creation and moves update PostHog.\\n\\n'",
                        'stty echo',
                        "printf '\\036' > /dev/ttyS1",
                        'exec /usr/bin/bash --rcfile /posthog/bin/shellrc -i',
                    ].join('\n') + '\n'
                )
                server.filesystem.file('init.sh', bin, async () => ({ bytes: setup })).size = setup.byteLength
                // Source setup from 9P to stay within the guest shell's input limit.
                // Parse the bootstrap together so stty cannot flush queued serial input.
                emulator.serial0_send(
                    'stty -echo; mkdir -p /posthog; umount /mnt; mount -t 9p -o trans=virtio,version=9p2000.L,cache=none host9p /posthog && . /posthog/bin/init.sh\n'
                )
            }
        })
    }

    write(data: string): void {
        if (this.ready) {
            this.atPrompt = false
            this.promptTail = ''
            this.emulator?.serial_send_bytes(0, new TextEncoder().encode(data))
        }
    }

    changeDirectory(folder: string): boolean {
        if (!this.disposed && !this.hasPrompt) {
            this.pendingDirectory = folder
            return true
        }
        if (!this.ready || this.disposed || !this.atPrompt) {
            return false
        }
        this.write(`cd -- '${folder.replaceAll("'", "'\\''")}'\n`)
        return true
    }

    read(): string {
        this.flushOutput()
        return this.output.slice(-1_000_000)
    }

    private flushOutput(): void {
        if (!this.outputLength || this.disposed) {
            return
        }
        const data = this.outputBuffer.slice(0, this.outputLength)
        this.outputLength = 0
        this.output += this.decoder.decode(data, { stream: true })
        if (this.output.length > 1_100_000) {
            this.output = this.output.slice(-1_000_000)
        }
        this.onOutput(data)
    }

    syncClock(): void {
        if (this.ready && !this.disposed) {
            const { timestamp, timezone } = browserClock()
            this.emulator?.serial_send_bytes(1, new TextEncoder().encode(`clock ${timestamp} ${timezone}\n`))
        }
    }

    resize(columns: number, rows: number): void {
        this.columns = Math.max(20, Math.min(500, Math.floor(columns)))
        this.rows = Math.max(5, Math.min(200, Math.floor(rows)))
        if (this.ready) {
            this.emulator?.serial_send_bytes(1, new TextEncoder().encode(`resize ${this.rows} ${this.columns}\n`))
        }
    }

    dispose(): void {
        this.detachDisplay()
        this.disposed = true
        this.ready = false
        // V86 cannot destroy its CPU until asynchronous WASM initialization has finished.
        if (this.emulatorLoaded) {
            void this.emulator?.destroy()
        }
        this.emulator = undefined
        this.output = ''
        this.outputLength = 0
    }
}
