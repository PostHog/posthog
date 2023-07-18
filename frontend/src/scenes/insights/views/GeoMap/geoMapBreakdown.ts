import { BreakdownType } from '~/types'

export function geoMapBreakdown(type: BreakdownType, precision = 8): string {
    return `geohashEncode(${type === 'person' ? 'person.' : ''}properties.$geoip_longitude, ${
        type === 'person' ? 'person.' : ''
    }properties.$geoip_latitude, ${Number(String(precision))}) -- GeoHash`
}
