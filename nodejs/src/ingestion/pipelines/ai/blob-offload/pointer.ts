/**
 * Versioned pointer URIs that replace offloaded binary payloads in AI event JSON.
 *
 * `phaiblob://v1/sha256/<hex>?mime=...&size=...` — the `v1` segment is a resolution-strategy
 * dispatch token: future storage strategies mint new versions and old rows keep resolving.
 * Pointers deliberately carry no physical location (bucket/region/team); the resolver owns
 * the mapping. This module is the only place pointer strings are built or interpreted.
 */
export interface BlobPointer {
    algo: 'sha256'
    hash: string
    mime: string
    size: number
}

export const POINTER_SCHEME = 'phaiblob://'

const HEX_64 = /^[0-9a-f]{64}$/

export function isBlobPointer(value: string): boolean {
    return value.startsWith(POINTER_SCHEME)
}

export function encodeBlobPointer(pointer: BlobPointer): string {
    const params = new URLSearchParams({ mime: pointer.mime, size: String(pointer.size) })
    return `${POINTER_SCHEME}v1/${pointer.algo}/${pointer.hash}?${params.toString()}`
}

export function parseBlobPointer(value: string): BlobPointer | null {
    if (!isBlobPointer(value)) {
        return null
    }
    let url: URL
    try {
        url = new URL(value)
    } catch {
        return null
    }
    if (url.hostname !== 'v1') {
        return null
    }
    const segments = url.pathname.split('/').filter((s) => s.length > 0)
    if (segments.length !== 2 || segments[0] !== 'sha256' || !HEX_64.test(segments[1])) {
        return null
    }
    const mime = url.searchParams.get('mime')
    const sizeRaw = url.searchParams.get('size')
    if (!mime || !sizeRaw || !/^\d+$/.test(sizeRaw)) {
        return null
    }
    return { algo: 'sha256', hash: segments[1], mime, size: parseInt(sizeRaw, 10) }
}
