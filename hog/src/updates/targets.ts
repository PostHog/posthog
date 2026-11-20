// install.sh, install.ps1 and the npm launcher compute the same ids on the machine they run on.
export interface Target {
    id: string
    bunTarget: string
    os: 'darwin' | 'linux' | 'win32'
    cpu: 'x64' | 'arm64'
    libc?: 'glibc' | 'musl'
}

// x64 builds use Bun's baseline runtime, which runs on CPUs without AVX2.
export const TARGETS: readonly Target[] = [
    { id: 'darwin-arm64', bunTarget: 'bun-darwin-arm64', os: 'darwin', cpu: 'arm64' },
    { id: 'darwin-x64', bunTarget: 'bun-darwin-x64-baseline', os: 'darwin', cpu: 'x64' },
    { id: 'linux-x64', bunTarget: 'bun-linux-x64-baseline', os: 'linux', cpu: 'x64', libc: 'glibc' },
    { id: 'linux-arm64', bunTarget: 'bun-linux-arm64', os: 'linux', cpu: 'arm64', libc: 'glibc' },
    { id: 'linux-x64-musl', bunTarget: 'bun-linux-x64-musl-baseline', os: 'linux', cpu: 'x64', libc: 'musl' },
    { id: 'linux-arm64-musl', bunTarget: 'bun-linux-arm64-musl', os: 'linux', cpu: 'arm64', libc: 'musl' },
    { id: 'windows-x64', bunTarget: 'bun-windows-x64-baseline', os: 'win32', cpu: 'x64' },
    { id: 'windows-arm64', bunTarget: 'bun-windows-arm64', os: 'win32', cpu: 'arm64' },
]

export function findTarget(id: string): Target {
    const target = TARGETS.find((candidate) => candidate.id === id)
    if (!target) {
        throw new Error(`Unknown target "${id}". Known targets: ${TARGETS.map((t) => t.id).join(', ')}`)
    }
    return target
}

export function binaryName(target: Target): string {
    return target.os === 'win32' ? 'hog.exe' : 'hog'
}

const RUST_ARCH = { x64: 'x86_64', arm64: 'aarch64' } as const

// The Rust triple release/build-worker.ts builds hog-worker for. Computed from the target, so every
// hog build has a worker build.
export function rustTarget(target: Target): string {
    const arch = RUST_ARCH[target.cpu]
    switch (target.os) {
        case 'darwin':
            return `${arch}-apple-darwin`
        case 'win32':
            return `${arch}-pc-windows-msvc`
        case 'linux':
            return `${arch}-unknown-linux-${target.libc === 'musl' ? 'musl' : 'gnu'}`
    }
}

// hog-worker does the file work of `hog error-tracking`, and hog starts it only from its own folder.
// So it ships next to hog in every archive and package, and every installer places the two together.
export function workerName(os: string): string {
    return os === 'win32' ? 'hog-worker.exe' : 'hog-worker'
}

export function shippedBinaries(target: Target): string[] {
    return [binaryName(target), workerName(target.os)]
}

export function archiveName(target: Target): string {
    return target.os === 'win32' ? `hog-${target.id}.zip` : `hog-${target.id}.tar.gz`
}

export function npmPackageName(target: Target): string {
    return `@posthog/hog-${target.id}`
}

export function targetFor(platform: string, arch: string, musl: boolean): Target | undefined {
    return TARGETS.find(
        (target) =>
            target.os === platform &&
            target.cpu === arch &&
            (target.os !== 'linux' || (target.libc === 'musl') === musl)
    )
}
