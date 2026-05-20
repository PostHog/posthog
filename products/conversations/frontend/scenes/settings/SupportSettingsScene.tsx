import { router } from 'kea-router'

import { SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'
import { SettingId } from 'scenes/settings/types'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'

export const CONVERSATIONS_LOGIC_KEY = 'conversationsSettings'

const VALID_SETTING_IDS = new Set<SettingId>([
    'conversations-general',
    'conversations-channels',
    'conversations-notifications',
])

const DEFAULT_SETTING_ID: SettingId = 'conversations-general'

function resolveSettingId(): SettingId {
    const candidate = router.values.hashParams.selectedSetting
    if (typeof candidate === 'string' && VALID_SETTING_IDS.has(candidate as SettingId)) {
        return candidate as SettingId
    }
    return DEFAULT_SETTING_ID
}

export const scene: SceneExport = {
    component: SupportSettingsScene,
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
                settingId={resolveSettingId()}
                handleLocally
            />
        </SceneContent>
    )
}
