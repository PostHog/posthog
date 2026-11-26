import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { PlatformAlertReceiverModal } from './PlatformAlertReceiverModal'
import { PlatformAlertReceiversTable } from './PlatformAlertReceiversTable'
import { PlatformAlertRouteModal } from './PlatformAlertRouteModal'
import { PlatformAlertRoutesTable } from './PlatformAlertRoutesTable'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'

export function PlatformAlertRouting(): JSX.Element {
    const { receivers, receiversError, routesError, editDisabledReason } = useValues(platformAlertRoutingLogic)
    const { openReceiverModal, openRouteModal, loadReceivers, loadRoutes } = useActions(platformAlertRoutingLogic)

    return (
        <div className="flex flex-col gap-6">
            <SceneSection
                title="Receivers"
                description="Destinations shared across the project. Routes decide which alerts each receiver hears about."
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => openReceiverModal(null)}
                        disabledReason={editDisabledReason}
                        data-attr="platform-alert-receiver-new"
                    >
                        New receiver
                    </LemonButton>
                }
            >
                {receiversError ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: () => loadReceivers(),
                            'data-attr': 'platform-alert-receivers-retry',
                        }}
                    >
                        Couldn't load receivers. Try again in a moment.
                    </LemonBanner>
                ) : (
                    <PlatformAlertReceiversTable />
                )}
            </SceneSection>
            <SceneSection
                title="Routes"
                description="Each route sends every alert whose labels match its conditions to a receiver, as well as to the alert's own destinations."
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => openRouteModal(null)}
                        disabledReason={editDisabledReason ?? (receivers?.length ? undefined : 'Add a receiver first')}
                        data-attr="platform-alert-route-new"
                    >
                        New route
                    </LemonButton>
                }
            >
                {routesError ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: () => loadRoutes(),
                            'data-attr': 'platform-alert-routes-retry',
                        }}
                    >
                        Couldn't load routes. Try again in a moment.
                    </LemonBanner>
                ) : (
                    <PlatformAlertRoutesTable />
                )}
            </SceneSection>
            <PlatformAlertReceiverModal />
            <PlatformAlertRouteModal />
        </div>
    )
}
