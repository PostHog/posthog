export interface Version {
    major: number
    minor: number
    patch: number
    prerelease: string[]
}

const SEMVER =
    /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$/

export function parseVersion(text: string): Version | undefined {
    const match = SEMVER.exec(text.trim())
    if (!match) {
        return undefined
    }
    return {
        major: Number(match[1]),
        minor: Number(match[2]),
        patch: Number(match[3]),
        prerelease: match[4] ? match[4].split('.') : [],
    }
}

function compareIdentifiers(a: string, b: string): number {
    const aNumber = /^\d+$/.test(a)
    const bNumber = /^\d+$/.test(b)
    if (aNumber && bNumber) {
        return Number(a) - Number(b)
    }
    if (aNumber !== bNumber) {
        return aNumber ? -1 : 1
    }
    return a < b ? -1 : a > b ? 1 : 0
}

// Semver precedence: 1.0.0-alpha.2 < 1.0.0-alpha.10 < 1.0.0 < 1.0.1.
export function compareVersions(a: Version, b: Version): number {
    const core = a.major - b.major || a.minor - b.minor || a.patch - b.patch
    if (core !== 0) {
        return Math.sign(core)
    }
    if (a.prerelease.length === 0 || b.prerelease.length === 0) {
        return Math.sign(b.prerelease.length - a.prerelease.length)
    }
    for (let index = 0; index < Math.max(a.prerelease.length, b.prerelease.length); index++) {
        const left = a.prerelease[index]
        const right = b.prerelease[index]
        if (left === undefined || right === undefined) {
            return left === undefined ? -1 : 1
        }
        const order = compareIdentifiers(left, right)
        if (order !== 0) {
            return Math.sign(order)
        }
    }
    return 0
}

export function isNewer(latest: string, current: string): boolean {
    const a = parseVersion(latest)
    const b = parseVersion(current)
    return a !== undefined && b !== undefined && compareVersions(a, b) > 0
}

const DAY_MS = 24 * 60 * 60 * 1000
export const STALE_AFTER_MS = 30 * DAY_MS

// A few patch releases within a month aren't worth a notice.
export function isMeaningfullyBehind(
    current: { version: string; buildDate: string },
    latest: { version: string; publishedAt: string }
): boolean {
    const running = parseVersion(current.version)
    const newest = parseVersion(latest.version)
    if (!running || !newest || compareVersions(newest, running) <= 0) {
        return false
    }

    if (newest.major !== running.major || newest.minor !== running.minor) {
        return true
    }

    const built = Date.parse(current.buildDate)
    const published = Date.parse(latest.publishedAt)
    return !Number.isNaN(built) && !Number.isNaN(published) && published - built > STALE_AFTER_MS
}
