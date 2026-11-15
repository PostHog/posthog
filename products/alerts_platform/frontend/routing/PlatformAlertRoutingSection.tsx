import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { PlatformAlertConfigurationApi, PlatformAlertOwnerEnumApi } from '../generated/api.schemas'
import { PlatformAlertRoutedReceivers } from './PlatformAlertRoutedReceivers'
import { routingUrl } from './platformAlertRoutingFormat'

export function PlatformAlertRoutingSection({
    configuration,
}: {
    configuration: PlatformAlertConfigurationApi
}): JSX.Element | null {
    const routingEnabled = useFeatureFlag('PLATFORM_ALERTS_ROUTING')
    // Delivery routes only platform-owned alerts. A source-owned alert's source sends its notifications.
    if (!routingEnabled || configuration.owner !== PlatformAlertOwnerEnumApi.Platform) {
        return null
    }
    return (
        <SceneSection
            title="Routing"
            description="Team-wide receivers this alert also notifies, because a route matches its labels."
            actions={
                <LemonButton type="secondary" size="small" to={routingUrl()} data-attr="platform-alert-manage-routing">
                    Manage routing
                </LemonButton>
            }
        >
            <PlatformAlertRoutedReceivers labels={configuration.labels} />
        </SceneSection>
    )
}
