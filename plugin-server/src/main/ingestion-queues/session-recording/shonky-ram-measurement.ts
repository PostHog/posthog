import { status } from '../../../utils/status'

// thanks chat gpt 🙈
function getStringByteSize(str: string): number {
    let size = 0
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i)
        size += char > 0x7f ? 2 : 1
    }
    return size
}

export function getMapByteSize(map: Map<any, any>): number {
    let totalSize = 0

    for (const [key, value] of map.entries()) {
        if (typeof key === 'string') {
            totalSize += getStringByteSize(key)
        } else if (typeof key === 'number') {
            totalSize += 8 // 64-bit floating point
        } else {
            status.warn('💾', `Unknown key type: ${typeof key} when estimating Map size. using 64 as a size guess`)
            totalSize += 64
        }

        if (typeof value === 'string') {
            totalSize += getStringByteSize(value)
        } else if (typeof value === 'number') {
            totalSize += 8 // 64-bit floating point
        } else {
            status.warn('💾', `Unknown key type: ${typeof key} when estimating Map size. using 64 as a size guess`)
            totalSize += 64
        }
    }

    return totalSize
}
