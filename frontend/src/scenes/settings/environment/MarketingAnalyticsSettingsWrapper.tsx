import { useValues } from 'kea'

import { MarketingAnalyticsSettings } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/MarketingAnalyticsSettings'

import { settingsLogic } from '../settingsLogic'

export function MarketingAnalyticsSettingsWrapper(): JSX.Element {
    const { selectedSectionId } = useValues(settingsLogic({ logicKey: 'settingsScene' }))

    return <MarketingAnalyticsSettings hideTitle hideBaseCurrency={!selectedSectionId} />
}
