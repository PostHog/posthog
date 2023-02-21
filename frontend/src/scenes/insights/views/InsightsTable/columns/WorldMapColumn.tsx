import { IndexedTrendResult } from 'scenes/trends/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { countryCodeToName } from '../../WorldMap'

export function WorldMapColumnTitle(): JSX.Element {
    return <PropertyKeyInfo disableIcon disablePopover value="$geoip_country_name" />
}

type WorldMapColumnItemProps = {
    item: IndexedTrendResult
}

export function WorldMapColumnItem({ item }: WorldMapColumnItemProps): JSX.Element {
    return countryCodeToName[item.breakdown_value as string]
}
