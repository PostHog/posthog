import { IndexedTrendResult } from 'scenes/trends/types'
import { decodeGeohash } from '../../GeoMap/decodeGeohash'

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
    const [latitude, longitude] = decodeGeohash(String(item.breakdown_value))
    return (
        <>
            {latitude} x {longitude}
        </>
    )
}
