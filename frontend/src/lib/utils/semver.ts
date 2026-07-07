export interface SemanticVersion {
    major: number
    minor?: number
    patch?: number
    extra?: string
}

export function parseVersion(version: string): SemanticVersion {
    // Regex to parse a semver string, can be just major, major.minor or major.minor.patch
    // if there is a hyphen thing ignore anything afterwards
    // strip a leading v if it exists
    const split = version.split('-', 2)
    version = split[0]
    const extra = split[1]
    const match = version.match(/^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$/)
    if (!match) {
        throw new Error(`Invalid semver string: ${version}`)
    }
    const [, major, minor, patch] = match
    const majorInt = parseInt(major, 10)
    const minorInt = minor != null ? parseInt(minor, 10) : undefined
    const patchInt = patch != null ? parseInt(patch, 10) : undefined

    if (isNaN(majorInt) || (minorInt != null && isNaN(minorInt)) || (patchInt != null && isNaN(patchInt))) {
        throw new Error(`Invalid semver string: ${version}`)
    }
    return { major: majorInt, minor: minorInt, patch: patchInt, extra }
}

export interface SemanticVersionDiff {
    kind: 'major' | 'minor' | 'patch' | 'extra'
    diff: number
}

export function diffVersions(a: string | SemanticVersion, b: string | SemanticVersion): SemanticVersionDiff | null {
    const pa = typeof a === 'string' ? parseVersion(a) : a
    const pb = typeof b === 'string' ? parseVersion(b) : b

    if (pa.major !== pb.major) {
        return { kind: 'major', diff: pa.major - pb.major }
    }
    if (pa.minor !== pb.minor) {
        return { kind: 'minor', diff: (pa.minor ?? 0) - (pb.minor ?? 0) }
    }
    if (pa.patch !== pb.patch) {
        return { kind: 'patch', diff: (pa.patch ?? 0) - (pb.patch ?? 0) }
    }
    if (pa.extra !== pb.extra) {
        // not having an extra is treated as a higher version than having an extra
        if (pa.extra) {
            if (pb.extra) {
                // we don't really use these, if we ever do we should improve this logic to better compare them,
                // for now just do a simple string comparison rather than trying to parse alpha/beta/rc/etc
                return { kind: 'extra', diff: pa.extra.localeCompare(pb.extra) }
            }

            return { kind: 'extra', diff: -1 }
        }
        if (pb.extra) {
            return { kind: 'extra', diff: 1 }
        }
        return null
    }
    return null
}

export function compareVersion(a: string | SemanticVersion, b: string | SemanticVersion): number {
    const diff = diffVersions(a, b)
    if (!diff) {
        return 0
    }
    return diff.diff
}

export function createVersionChecker(requiredVersion: string | SemanticVersion) {
    return (version: string | SemanticVersion): boolean => {
        const diff = diffVersions(version, requiredVersion)
        return !diff || diff.diff > 0
    }
}
