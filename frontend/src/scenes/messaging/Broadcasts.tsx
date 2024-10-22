import { IconPlusSmall } from '@posthog/icons'
import { BindLogic } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { broadcastsLogic } from 'scenes/messaging/broadcastsLogic'
import { MessagingTabs } from 'scenes/messaging/MessagingTabs'
import { DestinationsTable } from 'scenes/pipeline/destinations/Destinations'
import { pipelineDestinationsLogic } from 'scenes/pipeline/destinations/destinationsLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export function Broadcasts(): JSX.Element {
    return (
        <>
            <MessagingTabs key="tabs" />
            <PageHeader
                caption="Send one time communications to your users"
                buttons={
                    <LemonButton
                        data-attr="new-broadcast"
                        to={urls.messagingBroadcastNew()}
                        type="primary"
                        icon={<IconPlusSmall />}
                    >
                        New broadcast
                    </LemonButton>
                }
            />
            <BindLogic logic={pipelineDestinationsLogic} props={{ type: 'broadcast' }}>
                <DestinationsTable />
            </BindLogic>
        </>
    )
}

export const scene: SceneExport = {
    component: Broadcasts,
    logic: broadcastsLogic,
}
