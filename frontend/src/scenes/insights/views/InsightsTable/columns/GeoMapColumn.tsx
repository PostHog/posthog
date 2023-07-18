import { IndexedTrendResult } from 'scenes/trends/types'

function decodeGeohash(geohash: string): { latitude: number; longitude: number } {
    const BITS = [16, 8, 4, 2, 1]
    const BASE32 = '0123456789bcdefghjkmnpqrstuvwxyz'
    let is_even = true
    const lat: number[] = []
    const lon: number[] = []
    lat[0] = -90.0
    lat[1] = 90.0
    lon[0] = -180.0
    lon[1] = 180.0
    // let lat_err = 90.0
    // let lon_err = 180.0

    for (let i = 0; i < geohash.length; i++) {
        const c = geohash[i]
        const cd = BASE32.indexOf(c)
        for (let j = 0; j < 5; j++) {
            const mask = BITS[j]
            if (is_even) {
                // lon_err /= 2
                refineInterval(lon, cd, mask)
            } else {
                // lat_err /= 2
                refineInterval(lat, cd, mask)
            }
            is_even = !is_even
        }
    }
    lat[2] = (lat[0] + lat[1]) / 2
    lon[2] = (lon[0] + lon[1]) / 2

    return { latitude: lat[2], longitude: lon[2] }
}

function refineInterval(interval: number[], cd: number, mask: number): void {
    if (cd && mask) {
        interval[0] = (interval[0] + interval[1]) / 2
    } else {
        interval[1] = (interval[0] + interval[1]) / 2
    }
}

export function GeoMapColumnTitle(): JSX.Element {
    return <>Geo Map</>
}

type GeoMapColumnItemProps = {
    item: IndexedTrendResult
}

export function GeoMapColumnItem({ item }: GeoMapColumnItemProps): JSX.Element {
    if (!item.breakdown_value) {
        return <>N/A</>
    }
    const { latitude, longitude } = decodeGeohash(String(item.breakdown_value))
    return (
        <>
            {latitude} x {longitude}
        </>
    )
}
