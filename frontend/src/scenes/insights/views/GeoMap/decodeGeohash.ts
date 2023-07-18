const BASE32_CODES = '0123456789bcdefghjkmnpqrstuvwxyz'
const BASE32_CODES_DICT: { [index: string]: number } = {}
for (let i = 0; i < BASE32_CODES.length; i++) {
    BASE32_CODES_DICT[BASE32_CODES.charAt(i)] = i
}

const MAX_LAT = 90
const MIN_LAT = -90
const MAX_LON = 180
const MIN_LON = -180

function decodeBbox(hash_string: string): number[] {
    let isLon = true
    let maxLat = MAX_LAT
    let minLat = MIN_LAT
    let maxLon = MAX_LON
    let minLon = MIN_LON
    let mid

    let hashValue = 0
    for (let i = 0, l = hash_string.length; i < l; i++) {
        const code = hash_string[i].toLowerCase()
        hashValue = BASE32_CODES_DICT[code]

        for (let bits = 4; bits >= 0; bits--) {
            const bit = (hashValue >> bits) & 1
            if (isLon) {
                mid = (maxLon + minLon) / 2
                if (bit === 1) {
                    minLon = mid
                } else {
                    maxLon = mid
                }
            } else {
                mid = (maxLat + minLat) / 2
                if (bit === 1) {
                    minLat = mid
                } else {
                    maxLat = mid
                }
            }
            isLon = !isLon
        }
    }
    return [minLat, minLon, maxLat, maxLon]
}

export function decodeGeohash(hashString: string): [number, number] {
    const bbox = decodeBbox(hashString)
    const lat = (bbox[0] + bbox[2]) / 2
    const lon = (bbox[1] + bbox[3]) / 2
    return [lat, lon]
}
