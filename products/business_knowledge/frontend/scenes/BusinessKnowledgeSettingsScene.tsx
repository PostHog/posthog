import { IconBook } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgeTabs } from '../components/BusinessKnowledgeTabs'

export const BUSINESS_KNOWLEDGE_SETTINGS_LOGIC_KEY = 'businessKnowledgeSettings'

export const scene: SceneExport = {
    component: BusinessKnowledgeSettingsScene,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
}

export function BusinessKnowledgeSettingsScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files so PostHog AI can understand your business context, vision, and policies."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBook /> }}
            />
            <BusinessKnowledgeTabs activeTab="settings" />
            <Settings
                logicKey={BUSINESS_KNOWLEDGE_SETTINGS_LOGIC_KEY}
                sectionId="environment-business-knowledge"
                settingId="business-knowledge-learn-from-support"
                handleLocally
            />
        </SceneContent>
    )
}
