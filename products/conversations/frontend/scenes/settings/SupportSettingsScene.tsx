import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'
import { ApiSection } from './ApiSection'
import { EmailSection } from './EmailSection'
import { NotificationsSection } from './NotificationsSection'
import { SecretApiKeySection } from './SecretApiKeySection'
import { SlackSection } from './SlackSection'
import { WidgetSection } from './WidgetSection'
import { WorkflowsSection } from './WorkflowsSection'

export const scene: SceneExport = {
    component: SupportSettingsScene,
    productKey: ProductKey.CONVERSATIONS,
}

export function SupportSettingsScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const emailChannelEnabled = useFeatureFlag('PRODUCT_SUPPORT_EMAIL_CHANNEL')

    return (
        <SceneContent>
            <SceneTitleSection
                name="Support"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            <ApiSection />
            {currentTeam?.conversations_enabled && (
                <>
                    <NotificationsSection />
                    <SlackSection />
                    {emailChannelEnabled && <EmailSection />}
                    <WidgetSection />
                    <WorkflowsSection />
                    <SecretApiKeySection />
                </>
            )}
        </SceneContent>
    )
}
