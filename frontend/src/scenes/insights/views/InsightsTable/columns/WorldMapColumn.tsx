import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/geography/country'
import { IndexedTrendResult } from 'scenes/trends/types'

export function WorldMapColumnTitle(): JSX.Element {
    return <PropertyKeyInfo disableIcon disablePopover value="$geoip_country_name" />
}

type WorldMapColumnItemProps = {
    item: IndexedTrendResult
}

export function WorldMapColumnItem({ item }: WorldMapColumnItemProps): JSX.Element {
    return <>{COUNTRY_CODE_TO_LONG_NAME[item.breakdown_value as string] || 'none'}</>
}
