export function isIPAddressInRange(address: string, prefix: string): boolean {
    try {
        if (!address || !prefix) return false

        const [net, mask] = prefix.split('/')
        if (!net || !mask) return false

        const cidr = +mask
        if (isNaN(cidr) || cidr < 0) return false

        const v4 = address.includes('.') && net.includes('.')
        const v6 = !v4 && address.includes(':') && net.includes(':')
        if (!v4 && !v6) return false
        if ((v4 && cidr > 32) || (v6 && cidr > 128)) return false

        const aBytes = toBytes(address, v4)
        const nBytes = toBytes(net, v4)
        if (!aBytes || !nBytes) return false

        const fullBytes = cidr >> 3
        for (let i = 0; i < fullBytes; i++) if (aBytes[i] !== nBytes[i]) return false

        const bits = cidr & 7
        if (bits && fullBytes < aBytes.length) {
            const m = 0xff << (8 - bits)
            if ((aBytes[fullBytes] & m) !== (nBytes[fullBytes] & m)) return false
        }

        return true
    } catch {
        return false
    }
}

function toBytes(ip: string, isV4: boolean): Uint8Array | null {
    if (isV4) {
        const p = ip.split('.')
        if (p.length !== 4) return null

        const b = new Uint8Array(4)
        for (let i = 0; i < 4; i++) {
            const n = +p[i]
            if (isNaN(n) || n < 0 || n > 255 || p[i] !== n.toString()) return null
            b[i] = n
        }
        return b
    }

    const b = new Uint8Array(16)
    let s: string[]

    if (ip.includes('::')) {
        if ((ip.match(/::/g) || []).length > 1) return null

        const [pre, post] = ip.split('::')
        const preSeg = pre ? pre.split(':') : []
        const postSeg = post ? post.split(':') : []

        if (preSeg.length + postSeg.length > 7) return null

        s = [...preSeg, ...Array(8 - preSeg.length - postSeg.length).fill('0'), ...postSeg]
    } else {
        s = ip.split(':')
        if (s.length !== 8) return null
    }

    for (let i = 0; i < 8; i++) {
        if (!s[i] && s[i] !== '0') return null

        const v = parseInt(s[i], 16)
        if (isNaN(v) || v < 0 || v > 0xffff) return null

        b[i * 2] = v >> 8
        b[i * 2 + 1] = v & 0xff
    }
    return b
}
