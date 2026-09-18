import { V86 } from 'v86'
import wasmUrl from 'v86/build/v86.wasm?url'

import jqUrl from 'public/terminal/jq-linux-i386.bin?url'

import { NinePServer } from './ninepServer'

const FIRMWARE = 'https://raw.githubusercontent.com/copy/v86/589487c7758a2775f606ec631bd78609497f6e05/bios'

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
    private output = ''
    private decoder = new TextDecoder()
    private ready = false
    private disposed = false
    private columns = 80
    private rows = 24

    constructor(private onOutput: (bytes: Uint8Array) => void) {}

    async start(server: NinePServer, signal: AbortSignal, onReady: () => void): Promise<void> {
        const [bios, vgaBios, kernel, jq] = await Promise.all([
            verifiedImage(
                `${FIRMWARE}/seabios.bin`,
                '73e3f359102e3a9982c35fce98eb7cd08f18303ac7f1ba6ebfbe6cdc1c244d98',
                signal
            ),
            verifiedImage(
                `${FIRMWARE}/vgabios.bin`,
                'a4bc0d80cc3ca028c73dafa8fee396b8d054ce87ebd8abfbd31b06b437607880',
                signal
            ),
            verifiedImage(
                // This image's uncached 9P reads work before API file sizes are known; Linux 6.8 clamps them to zero.
                'https://i.copy.sh/buildroot-bzimage.bin',
                '7befbaea31e249d9a518c4b95fa42b2a193d0e3de46250d617cbdeb866ee28b0',
                signal
            ),
            verifiedImage(jqUrl, 'ba996e8ce436973e2f39e2639405a37e8c81ba8c722b71c83996278ad0af16dd', signal),
        ])
        if (signal.aborted || this.disposed) {
            return
        }
        const bin = server.filesystem.directory('bin', server.filesystem.root)
        server.filesystem.file('jq', bin, async () => ({ bytes: new Uint8Array(jq) })).size = jq.byteLength
        const emulator = (this.emulator = new V86({
            wasm_path: wasmUrl,
            bios: { buffer: bios },
            vga_bios: { buffer: vgaBios },
            bzimage: { buffer: kernel },
            memory_size: 128 * 1024 * 1024,
            filesystem: { handle9p: server.handle },
            cmdline: 'tsc=reliable mitigations=off random.trust_cpu=on',
            disable_keyboard: true,
            disable_mouse: true,
            disable_speaker: true,
            uart1: true,
            autostart: true,
        }))
        let boot = ''
        let configured = false
        emulator.add_listener('serial1-output-byte', (byte: number) => {
            if (configured && !this.ready && byte === 30) {
                this.ready = true
                this.resize(this.columns, this.rows)
                onReady()
            }
        })
        emulator.add_listener('serial0-output-byte', (byte: number) => {
            const data = Uint8Array.of(byte)
            this.output = (this.output + this.decoder.decode(data, { stream: true })).slice(-1_000_000)
            this.onOutput(data)
            if (this.ready) {
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
                        'cp /posthog/bin/jq /usr/bin/jq && chmod +x /usr/bin/jq || exit',
                        'cp /posthog/bin/ph /usr/bin/ph && chmod +x /usr/bin/ph || exit',
                        'stty -F /dev/ttyS1 raw -echo',
                        // Detach the control helper so the shell's wait command only waits for user jobs.
                        '(while read -r command first second; do case "$command" in resize) stty -F /dev/ttyS0 rows "$first" cols "$second";; clock) date -s "@$first" > /dev/null; printf "%s\\n" "$second" > /etc/TZ;; esac; done < /dev/ttyS1 &)',
                        "alias ls='ls --color=auto'",
                        "export PS1='\\[\\033[32m\\]posthog\\[\\033[0m\\]:\\[\\033[34m\\]\\w\\[\\033[0m\\] $ '",
                        'cd /posthog/files',
                        'clear',
                        'printf \'PostHog terminal\\n\\nTry:\\n  ls --color=auto\\n  find . -name "*.md"\\n  vi Unfiled/Notebooks/Foobar.md\\n  mkdir Research\\n  ph tools\\n  ph notebooks-list --limit 10 | jq .\\n  cat /posthog/README.txt\\n\\nUse your own notebook path with vi. Save with :wq; quit with :q!.\\nSelecting text copies it. Folder creation and moves update PostHog.\\n\\n\'',
                        'stty echo',
                        "printf '\\036' > /dev/ttyS1",
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
            this.emulator?.serial_send_bytes(0, new TextEncoder().encode(data))
        }
    }

    read(): string {
        return this.output
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
        this.disposed = true
        this.emulator?.destroy()
    }
}
