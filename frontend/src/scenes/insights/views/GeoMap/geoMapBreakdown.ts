import { BreakdownType } from '~/types'

export function geoMapBreakdown(type: BreakdownType, precision = 5): string {
    return `geohashEncode(${type === 'person' ? 'person.' : ''}properties.$geoip_latitude, ${
        type === 'person' ? 'person.' : ''
    }properties.$geoip_longitude, ${Number(String(precision))}) -- GeoHash`
}
