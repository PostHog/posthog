// Port of symbolic-common 12.x `join_path` and `clean_path` (src/path.rs), Windows rules included.

const isSep = (c: string | undefined): boolean => c === '/' || c === '\\'

function isWindowsUnc(p: string): boolean {
    return p.startsWith('\\\\') || p.startsWith('//')
}

function isWindowsDriveLetter(p: string): boolean {
    const d = p.charCodeAt(0)
    const alpha = (d >= 0x41 && d <= 0x5a) || (d >= 0x61 && d <= 0x7a)
    return alpha && p[1] === ':' && (p.length === 2 || isSep(p[2]))
}

const isAbsoluteWindows = (p: string): boolean => isWindowsUnc(p) || isWindowsDriveLetter(p)
const isSemiAbsoluteWindows = (p: string): boolean => isSep(p[0])
const isAbsoluteUnix = (p: string): boolean => p[0] === '/'
const isWindowsPath = (p: string): boolean => isAbsoluteWindows(p) || p.includes('\\')

function trimEndSeps(s: string): string {
    let e = s.length
    while (e > 0 && isSep(s[e - 1])) {
        e--
    }
    return s.slice(0, e)
}

function trimStartSeps(s: string): string {
    let b = 0
    while (b < s.length && isSep(s[b])) {
        b++
    }
    return s.slice(b)
}

export function joinPath(base: string, other: string): string {
    if (other.startsWith('<') && other.endsWith('>')) {
        return other
    }
    if (base === '' || isAbsoluteWindows(other) || isAbsoluteUnix(other)) {
        return other
    }
    if (other === '') {
        return base
    }
    if (isSemiAbsoluteWindows(other)) {
        // C:\test + \bar -> C:\bar
        return isAbsoluteWindows(base) ? base.slice(0, 2) + other : other
    }
    const win = isWindowsPath(base) || isWindowsPath(other)
    return trimEndSeps(base) + (win ? '\\' : '/') + trimStartSeps(other)
}

function rfindSep(s: string): number {
    for (let i = s.length - 1; i >= 0; i--) {
        if (isSep(s[i])) {
            return i
        }
    }
    return -1
}

export function cleanPath(path: string): string {
    let rv = ''
    const sep = isWindowsPath(path) ? '\\' : '/'
    let needsSeparator = false
    let isPastRoot = false

    // Rust `split_terminator`: like split, minus one trailing empty segment.
    const segments = path.split(/[\\/]/)
    if (segments.length > 0 && segments[segments.length - 1] === '') {
        segments.pop()
    }

    for (const segment of segments) {
        if (segment === '.') {
            continue
        }
        if (segment === '..') {
            let popped = false
            if (!isPastRoot) {
                const idx = rfindSep(rv)
                if (idx >= 0) {
                    rv = rv.slice(0, idx)
                    popped = true
                } else if (rv !== '') {
                    rv = ''
                    popped = true
                }
            }
            if (popped) {
                if (rv === '') {
                    needsSeparator = false
                }
            } else {
                if (!isPastRoot) {
                    needsSeparator = false
                    isPastRoot = true
                }
                if (needsSeparator) {
                    rv += sep
                }
                rv += '..'
                needsSeparator = true
            }
            continue
        }
        if (needsSeparator) {
            rv += sep
        } else {
            needsSeparator = true
        }
        rv += segment
    }
    return rv
}
