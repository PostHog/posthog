import { useValues } from 'kea'
import { router } from 'kea-router'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'
import type { SettingId } from 'scenes/settings/types'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgeTabs } from '../../components/BusinessKnowledgeTabs/BusinessKnowledgeTabs'

export const BUSINESS_KNOWLEDGE_SETTINGS_LOGIC_KEY = 'businessKnowledgeSettings'

const DEFAULT_SETTING_ID: SettingId = 'business-knowledge-learn-from-support'
const SETTING_IDS: SettingId[] = [DEFAULT_SETTING_ID, 'business-knowledge-github-repos']

export const scene: SceneExport = {
    component: BusinessKnowledgeSettingsScene,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
}

export function BusinessKnowledgeSettingsScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const { hashParams } = useValues(router)
    const linkedSettingId = SETTING_IDS.find((id) => id === hashParams.selectedSetting)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files so AI can understand your business context, vision, and policies."
                resourceType={{ type: 'business_knowledge' }}
            />
            <BusinessKnowledgeTabs activeTab="settings" />
            <Settings
                logicKey={BUSINESS_KNOWLEDGE_SETTINGS_LOGIC_KEY}
                sectionId="environment-business-knowledge"
                settingId={linkedSettingId ?? DEFAULT_SETTING_ID}
                handleLocally
            />
        </SceneContent>
    )
}
