import { useState } from 'react'

import { IconGlobe } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'

import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/geography/country'

import { BreakdownLiveCard } from './BreakdownLiveCard'
import { buildCityKey, CityBreakdownItem, CountryBreakdownItem } from './LiveWebAnalyticsMetricsTypes'

type LocationTab = 'country' | 'city'

interface LiveLocationsCardProps {
    countryData: CountryBreakdownItem[]
    cityData: CityBreakdownItem[]
    isLoading?: boolean
}

const renderFlagOrGlobe = (countryCode: string): JSX.Element => {
    if (!countryCode || countryCode === 'Other') {
        return <IconGlobe className="w-4 h-4 flex-shrink-0 text-muted" />
    }
    return (
        <span
            className="w-4 h-4 inline-flex items-center justify-center text-base leading-none flex-shrink-0"
            aria-hidden
        >
            {countryCodeToFlag(countryCode)}
        </span>
    )
}

const getCountryKey = (d: CountryBreakdownItem): string => d.country
const getCountryLabel = (d: CountryBreakdownItem): string => COUNTRY_CODE_TO_LONG_NAME[d.country] ?? d.country
const renderCountryIcon = (d: CountryBreakdownItem): JSX.Element => renderFlagOrGlobe(d.country)

const getCityKey = (d: CityBreakdownItem): string =>
    d.cityName === 'Other' ? 'Other' : buildCityKey(d.cityName, d.countryCode)
const getCityLabel = (d: CityBreakdownItem): string => {
    if (d.cityName === 'Other') {
        return 'Other'
    }
    return d.countryCode ? `${d.cityName}, ${d.countryCode}` : d.cityName
}
const renderCityIcon = (d: CityBreakdownItem): JSX.Element =>
    renderFlagOrGlobe(d.cityName === 'Other' ? 'Other' : d.countryCode)

export const LiveLocationsCard = ({ countryData, cityData, isLoading }: LiveLocationsCardProps): JSX.Element => {
    const [activeTab, setActiveTab] = useState<LocationTab>('country')

    const tabs = (
        <LemonTabs<LocationTab>
            activeKey={activeTab}
            onChange={setActiveTab}
            size="small"
            tabs={[
                { key: 'country', label: 'Country' },
                { key: 'city', label: 'City' },
            ]}
        />
    )

    if (activeTab === 'city') {
        return (
            <BreakdownLiveCard<CityBreakdownItem>
                title={tabs}
                data={cityData}
                getKey={getCityKey}
                getLabel={getCityLabel}
                renderIcon={renderCityIcon}
                emptyMessage="No city data"
                statLabel="unique visitors"
                isLoading={isLoading}
            />
        )
    }

    return (
        <BreakdownLiveCard<CountryBreakdownItem>
            title={tabs}
            data={countryData}
            getKey={getCountryKey}
            getLabel={getCountryLabel}
            renderIcon={renderCountryIcon}
            emptyMessage="No country data"
            statLabel="unique visitors"
            isLoading={isLoading}
        />
    )
}
