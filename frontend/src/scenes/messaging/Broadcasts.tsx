import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { broadcastsLogic } from 'scenes/messaging/broadcastsLogic'
import { FunctionsTable } from 'scenes/messaging/FunctionsTable'
import { MessagingTabs } from 'scenes/messaging/MessagingTabs'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export function Broadcasts(): JSX.Element {
    const { broadcastId } = useValues(broadcastsLogic)
    return broadcastId ? (
        <HogFunctionConfiguration
            id={broadcastId === 'new' ? null : broadcastId}
            templateId={broadcastId === 'new' ? 'template-new-broadcast' : ''}
        />
    ) : (
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
            <FunctionsTable type="broadcast" />
        </>
    )
}

export const scene: SceneExport = {
    component: Broadcasts,
    logic: broadcastsLogic,
}
