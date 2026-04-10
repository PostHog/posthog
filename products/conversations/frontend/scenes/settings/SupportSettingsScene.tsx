import { router } from 'kea-router'

import { SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'

export const CONVERSATIONS_LOGIC_KEY = 'conversationsSettings'

export const scene: SceneExport = {
    component: SupportSettingsScene,
    productKey: ProductKey.CONVERSATIONS,
}

export function SupportSettingsScene(): JSX.Element {
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
            <Settings
                logicKey={CONVERSATIONS_LOGIC_KEY}
                sectionId="environment-conversations"
                settingId={router.values.hashParams.selectedSetting || 'conversations-api'}
                handleLocally
            />
        </SceneContent>
    )
}
