import { router } from 'kea-router'

import { SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'
import { CONVERSATIONS_LOGIC_KEY, resolveSettingId, supportSettingsSceneLogic } from './supportSettingsSceneLogic'

export const scene: SceneExport = {
    component: SupportSettingsScene,
    logic: supportSettingsSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
}

export function SupportSettingsScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Support"
                description="Receive customer questions over web, email, Slack, and Microsoft Teams. Triage, assign, and automate responses."
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            <Settings
                logicKey={CONVERSATIONS_LOGIC_KEY}
                sectionId="environment-conversations"
                settingId={resolveSettingId(router.values.hashParams)}
                handleLocally
            />
        </SceneContent>
    )
}
