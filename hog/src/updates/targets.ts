// Every platform hog ships a binary for. The id is the name people see in archive and npm package
// names, and install.sh, install.ps1 and the npm launcher compute the same id on the machine they run on.
export interface Target {
    id: string
    bunTarget: string
    os: 'darwin' | 'linux' | 'win32'
    cpu: 'x64' | 'arm64'
    libc?: 'glibc' | 'musl'
}

export const TARGETS: readonly Target[] = [
    { id: 'darwin-arm64', bunTarget: 'bun-darwin-arm64', os: 'darwin', cpu: 'arm64' },
    { id: 'darwin-x64', bunTarget: 'bun-darwin-x64', os: 'darwin', cpu: 'x64' },
    { id: 'linux-x64', bunTarget: 'bun-linux-x64', os: 'linux', cpu: 'x64', libc: 'glibc' },
    { id: 'linux-arm64', bunTarget: 'bun-linux-arm64', os: 'linux', cpu: 'arm64', libc: 'glibc' },
    { id: 'linux-x64-musl', bunTarget: 'bun-linux-x64-musl', os: 'linux', cpu: 'x64', libc: 'musl' },
    { id: 'linux-arm64-musl', bunTarget: 'bun-linux-arm64-musl', os: 'linux', cpu: 'arm64', libc: 'musl' },
    { id: 'windows-x64', bunTarget: 'bun-windows-x64', os: 'win32', cpu: 'x64' },
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

export function archiveName(target: Target): string {
    return target.os === 'win32' ? `hog-${target.id}.zip` : `hog-${target.id}.tar.gz`
}

export function npmPackageName(target: Target): string {
    return `@posthog/hog-${target.id}`
}

// The target of the machine hog runs on, or undefined when hog has no build for it. install.sh and the
// npm launcher make the same choice.
export function targetFor(platform: string, arch: string, musl: boolean): Target | undefined {
    return TARGETS.find(
        (target) =>
            target.os === platform &&
            target.cpu === arch &&
            (target.os !== 'linux' || (target.libc === 'musl') === musl)
    )
}
