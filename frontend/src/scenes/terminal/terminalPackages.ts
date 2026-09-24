import manifest from './terminal-packages.json'
import { TerminalFilesystem } from './terminalFilesystem'

export interface TerminalPackage {
    name: string
    version: string
    file: string
    baseUrl?: string
    sha256: string
    size: number
    archiveSize: number
    dependencies: string[]
    commands: Record<string, string>
}

const CACHE_NAME = 'posthog-terminal-packages-v1'

// Doom configuration stores keyboard bindings as PC scancodes.
const DOOM_CONFIG = `key_up 17
key_down 31
key_strafeleft 30
key_straferight 32
key_left 75
key_right 77
key_fire 57
key_use 18
key_speed 42
use_mouse 1
mouseb_fire 0
mouseb_strafe -1
mouseb_forward -1
mouse_sensitivity 5
`

export class TerminalPackages {
    private downloads = new Map<string, Promise<Uint8Array>>()

    constructor(
        private filesystem: TerminalFilesystem,
        private signal: AbortSignal,
        private packages: Record<string, TerminalPackage> = manifest.packages,
        private baseUrl: string = manifest.baseUrl
    ) {}

    private async download(pkg: TerminalPackage): Promise<Uint8Array> {
        const url = `${pkg.baseUrl ?? this.baseUrl}/${pkg.file}`
        let cache: Cache | undefined
        try {
            cache = await globalThis.caches?.open(CACHE_NAME)
        } catch {
            // Private browsing and storage quotas must not prevent installation.
        }
        const cached = await cache?.match(url).catch(() => undefined)
        const response =
            cached ??
            (await fetch(url, {
                signal: AbortSignal.any([this.signal, AbortSignal.timeout(120_000)]),
                credentials: 'omit',
                referrerPolicy: 'no-referrer',
                redirect: 'error',
            }))
        if (!response.ok) {
            throw new Error(`Could not download ${pkg.name}. Run the command again to retry.`)
        }
        const compressed = await response.arrayBuffer()
        const digest = await crypto.subtle.digest('SHA-256', compressed)
        const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
        if (compressed.byteLength !== pkg.size || actual !== pkg.sha256) {
            await cache?.delete(url).catch(() => false)
            throw new Error(`Could not verify ${pkg.name}. Run the command again to download a fresh copy.`)
        }
        if (this.signal.aborted) {
            throw new DOMException('Terminal closed', 'AbortError')
        }
        const archive = await new Response(
            new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))
        ).arrayBuffer()
        if (archive.byteLength !== pkg.archiveSize) {
            throw new Error(`Could not unpack ${pkg.name}. Reload PostHog and try again.`)
        }
        if (this.signal.aborted) {
            throw new DOMException('Terminal closed', 'AbortError')
        }
        if (!cached) {
            await cache?.put(url, new Response(compressed)).catch(() => undefined)
        }
        return new Uint8Array(archive)
    }

    mount(): void {
        const directory = this.filesystem.directory('packages', this.filesystem.root)
        const bin = this.filesystem.directory('bin', this.filesystem.root)
        const config = this.filesystem.directory('config', this.filesystem.root)
        this.filesystem.text('doom.cfg', config, DOOM_CONFIG)
        const cases: string[] = []
        for (const [id, pkg] of Object.entries(this.packages)) {
            this.filesystem.file(`${id}.tar`, directory, async () => {
                let download = this.downloads.get(id)
                if (!download) {
                    download = this.download(pkg).finally(() => this.downloads.delete(id))
                    this.downloads.set(id, download)
                }
                return { bytes: await download }
            }).size = pkg.archiveSize
            cases.push(`${id}) name='${pkg.name}'; version='${pkg.version}';;`)
            for (const [command, entrypoint] of Object.entries(pkg.commands)) {
                this.filesystem.text(
                    command,
                    bin,
                    [
                        '#!/bin/sh',
                        ...[...pkg.dependencies, id].map(
                            (dependency) => `sh /posthog/bin/install-tool ${dependency} || exit $?`
                        ),
                        ...(command === 'doom'
                            ? [
                                  'mkdir -p /tmp/doom',
                                  '[ -f /tmp/doom/posthog-controls.cfg ] || cp /posthog/config/doom.cfg /tmp/doom/posthog-controls.cfg',
                                  `exec ${entrypoint} "$@" -config /tmp/doom/posthog-controls.cfg`,
                              ]
                            : [`exec ${entrypoint} "$@"`]),
                        '',
                    ].join('\n')
                )
            }
        }
        this.filesystem.text(
            'install-tool',
            bin,
            `#!/bin/sh
set -eu
id="$1"
case "$id" in
${cases.join('\n')}
*) echo 'Unknown terminal tool. Reload PostHog and try again.' >&2; exit 1;;
esac
root=/opt/posthog-packages
target="$root/$id-$version"
[ -d "$target" ] && exit 0
mkdir -p "$root"
lock="$root/.$id.lock"
attempt=0
while ! mkdir "$lock" 2>/dev/null; do
    [ -d "$target" ] && exit 0
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 120 ]; then
        echo 'Another installation is still running. Close and reopen the terminal to retry.' >&2
        exit 1
    fi
    sleep 1
done
stage="$root/.$id-$$"
trap 'rm -rf "$stage"; rmdir "$lock"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
[ -d "$target" ] && exit 0
printf 'Installing %s %s...\\n' "$name" "$version" >&2
mkdir "$stage"
if ! tar -xf "/posthog/packages/$id.tar" -C "$stage"; then
    echo 'Installation failed. Run the command again to retry.' >&2
    exit 1
fi
mv "$stage" "$target"
`
        )
    }
}
