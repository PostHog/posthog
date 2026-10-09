import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { CloudAgentsSceneShell } from '../components/CloudAgentsSceneShell'
import { SubscriptionsSection } from '../components/SubscriptionsSection'
import { TeamDefaultsSection } from '../components/TeamDefaultsSection'
import { WebhooksSection } from '../components/WebhooksSection'
import { CloudAgentsSceneLogicProps, cloudAgentsSceneLogic } from '../logics/cloudAgentsSceneLogic'

export const scene: SceneExport<CloudAgentsSceneLogicProps> = {
    component: CloudAgentsSettingsScene,
    logic: cloudAgentsSceneLogic,
    paramsToProps: () => ({ scene: 'settings' }),
    productKey: ProductKey.CLOUD_AGENTS,
}

export function CloudAgentsSettingsScene(): JSX.Element {
    return (
        <CloudAgentsSceneShell activeTab="settings">
            <TeamDefaultsSection />
            <SubscriptionsSection />
            <WebhooksSection />
        </CloudAgentsSceneShell>
    )
}
