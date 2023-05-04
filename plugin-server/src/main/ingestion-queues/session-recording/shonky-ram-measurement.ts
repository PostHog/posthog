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

function guesstimateValueSize(value: any, key: any) {
    let guesstimate = 0
    if (typeof value === 'string') {
        guesstimate += getStringByteSize(value)
    } else if (typeof value === 'number') {
        guesstimate += 8 // 64-bit floating point
    } else if (Array.isArray(value)) {
        guesstimate += value.reduce((acc, val) => {
            return acc + guesstimateValueSize(val, key)
        }, 0)
    } else {
        status.warn(
            '💾',
            `Unknown value type: ${typeof value} for key: ${key} when estimating Map size. using 64 as a size guess`
        )
        guesstimate += 64
    }
    return guesstimate
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

        totalSize = guesstimateValueSize(value, key)
    }

    return totalSize
}
