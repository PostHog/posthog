import { V86 } from 'v86'
import wasmUrl from 'v86/build/v86.wasm?url'

import doomUrl from 'public/terminal/fbdoom-linux-i386.bin?url'
import wadUrl from 'public/terminal/freedoom1.wad.gz.bin?url'
import jqUrl from 'public/terminal/jq-linux-i386.bin?url'
import kernelUrl from 'public/terminal/linux-fb-bzimage.bin?url'
import toolsUrl from 'public/terminal/tools-linux-i386.tar.gz.bin?url'

import { NinePServer } from './ninepServer'

const FIRMWARE = 'https://raw.githubusercontent.com/copy/v86/589487c7758a2775f606ec631bd78609497f6e05/bios'

const DOOM_SCRIPT = String.raw`#!/bin/sh
set -eu
if [ ! -x /tmp/fbdoom ]; then
    echo 'Downloading Doom (about 28 MB)...'
    cp /posthog/bin/fbdoom /tmp/fbdoom && chmod +x /tmp/fbdoom
    cp /posthog/bin/freedoom1.wad /tmp/freedoom1.wad
fi
# The first console already has a shell reading its keys, so Doom takes an unused one.
# Ctrl+C reaches this script as well as Doom, so the console is restored from a trap.
trap "printf '\\033[?25h' > /dev/tty5; display off; chvt 1" EXIT
trap 'exit 0' INT TERM
chvt 5
printf '\033[?25l' > /dev/tty5
display on
cd /tmp
/tmp/fbdoom -iwad /tmp/freedoom1.wad "$@" > /tmp/doom.log 2>&1 || true
`

const DISPLAY_SCRIPT = String.raw`#!/bin/sh
case "$1" in
    on) printf '\021' > /dev/ttyS1 ;;
    off) printf '\022' > /dev/ttyS1 ;;
    *) echo 'Usage: display on|off' >&2; exit 1 ;;
esac
`

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

function gunzip(buffer: ArrayBuffer): Promise<ArrayBuffer> {
    return new Response(new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer()
}

export class TerminalRuntime {
    private emulator?: V86
    private output = ''
    private decoder = new TextDecoder()
    private ready = false
    private disposed = false
    private columns = 80
    private rows = 24
    private displayInput = false

    constructor(
        private onOutput: (bytes: Uint8Array) => void,
        private screen: HTMLElement,
        private onDisplay: (active: boolean) => void
    ) {}

    async start(server: NinePServer, signal: AbortSignal, onReady: () => void): Promise<void> {
        const [bios, vgaBios, kernel, jq, tools] = await Promise.all([
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
                // Linux 5.6 serves uncached 9P reads before API file sizes are known; Linux 6.8 clamps them to zero.
                kernelUrl,
                '33ca60bd4832f0cf202845fa7ac1a60776c0215e8a20d21a3f07d3722f99e415',
                signal
            ),
            verifiedImage(jqUrl, 'ba996e8ce436973e2f39e2639405a37e8c81ba8c722b71c83996278ad0af16dd', signal),
            verifiedImage(toolsUrl, '50c8d847c3811249d512245b0b506cfab5cc4b625cc5fa6079cb605a7681b2cc', signal),
        ])
        if (signal.aborted || this.disposed) {
            return
        }
        // The guest's BusyBox tar has no gzip support.
        const toolsArchive = await gunzip(tools)
        if (signal.aborted || this.disposed) {
            return
        }
        const bin = server.filesystem.directory('bin', server.filesystem.root)
        server.filesystem.file('jq', bin, async () => ({ bytes: new Uint8Array(jq) })).size = jq.byteLength
        server.filesystem.file('tools.tar', bin, async () => ({ bytes: new Uint8Array(toolsArchive) })).size =
            toolsArchive.byteLength
        // Doom downloads on first use, because the game data is larger than everything else combined.
        const lazy = (name: string, url: string, sha256: string, size: number, gzipped = false): void => {
            let bytes: Promise<Uint8Array> | undefined
            server.filesystem.file(name, bin, async () => {
                bytes ??= verifiedImage(url, sha256, signal)
                    .then((buffer) => (gzipped ? gunzip(buffer) : buffer))
                    .then((buffer) => new Uint8Array(buffer))
                return { bytes: await bytes.catch((error) => ((bytes = undefined), Promise.reject(error))) }
            }).size = size
        }
        lazy('fbdoom', doomUrl, '0a8f549829c113eff1cd1490b2a9a502596490f9a4880d75fdb0d93acc2f01ae', 417_984)
        lazy(
            'freedoom1.wad',
            wadUrl,
            '8dfc9bcdb4b96809e69c516209048d46cc99d4fdd5e3179a6aaa98f7fe9491e1',
            28_795_076,
            true
        )
        server.filesystem.text('doom', bin, DOOM_SCRIPT)
        server.filesystem.text('display', bin, DISPLAY_SCRIPT)
        const emulator = (this.emulator = new V86({
            wasm_path: wasmUrl,
            bios: { buffer: bios },
            vga_bios: { buffer: vgaBios },
            bzimage: { buffer: kernel },
            memory_size: 128 * 1024 * 1024,
            vga_memory_size: 8 * 1024 * 1024,
            filesystem: { handle9p: server.handle },
            cmdline: 'tsc=reliable mitigations=off random.trust_cpu=on video=640x480',
            screen: { container: this.screen, use_graphical_text: true },
            disable_speaker: true,
            uart1: true,
            autostart: true,
        }))
        // v86 listens for keys on the whole window, so the display only takes input while it has focus.
        // Its input adapters do not exist until the emulator is ready.
        emulator.add_listener('emulator-ready', () => this.setDisplayInput(this.displayInput))
        let boot = ''
        let configured = false
        emulator.add_listener('serial1-output-byte', (byte: number) => {
            // The guest's display command sends DC1 when a graphical program starts and DC2 when it exits.
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
                        'tar -xf /posthog/bin/tools.tar -C / || exit',
                        'export EDITOR=nano VISUAL=nano',
                        'cp /posthog/bin/jq /usr/bin/jq && chmod +x /usr/bin/jq || exit',
                        'cp /posthog/bin/ph /usr/bin/ph && chmod +x /usr/bin/ph || exit',
                        'cp /posthog/bin/doom /usr/bin/doom && chmod +x /usr/bin/doom || exit',
                        'cp /posthog/bin/display /usr/bin/display && chmod +x /usr/bin/display || exit',
                        'stty -F /dev/ttyS1 raw -echo',
                        // Detach the control helper so the shell's wait command only waits for user jobs.
                        '(while read -r command first second; do case "$command" in resize) stty -F /dev/ttyS0 rows "$first" cols "$second";; clock) date -s "@$first" > /dev/null; printf "%s\\n" "$second" > /etc/TZ;; esac; done < /dev/ttyS1 &)',
                        "alias ls='ls --color=auto'",
                        "export PS1='\\[\\033[32m\\]posthog\\[\\033[0m\\]:\\[\\033[34m\\]\\w\\[\\033[0m\\] $ '",
                        'cd /posthog/files',
                        'clear',
                        "printf 'PostHog terminal\\n\\nTry:\\n  mc\\n  tree -C -L 3\\n  nano Unfiled/Notebooks/Foobar.md\\n  vi Unfiled/Notebooks/Foobar.md\\n  ncdu -r /posthog/files\\n  mkdir Research\\n  ph tools\\n  ph notebooks-list --limit 10 | jq .\\n  cat /posthog/README.txt\\n\\nUse your own notebook path. In nano, Ctrl+S saves and Ctrl+X exits.\\nIn vi, save with :wq; quit with :q!. Selecting text copies it.\\nFolder creation and moves update PostHog.\\n\\n'",
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

    setDisplayInput(enabled: boolean): void {
        this.displayInput = enabled
        this.emulator?.keyboard_set_enabled(enabled)
        this.emulator?.mouse_set_enabled(enabled)
    }

    interrupt(): void {
        this.emulator?.serial_send_bytes(0, Uint8Array.of(3))
    }

    fullscreen(): void {
        this.emulator?.screen_go_fullscreen()
    }

    captureMouse(): void {
        this.emulator?.lock_mouse()
    }

    dispose(): void {
        this.disposed = true
        this.emulator?.destroy()
    }
}
