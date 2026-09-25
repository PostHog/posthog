import { IconBook } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgeTabs } from '../components/BusinessKnowledgeTabs'
import { businessKnowledgePlaygroundLogic } from './businessKnowledgePlaygroundLogic'
import { PlaygroundChatList } from './PlaygroundChatList'
import { PlaygroundThread } from './PlaygroundThread'

export const scene: SceneExport = {
    component: BusinessKnowledgePlaygroundScene,
    logic: businessKnowledgePlaygroundLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
}

export function BusinessKnowledgePlaygroundScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent className="min-h-0 flex-1 overflow-hidden">
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files so PostHog AI can understand your business context, vision, and policies."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBook /> }}
            />
            <BusinessKnowledgeTabs activeTab="playground" />
            {/* 521px: a 520px scene stacks the list above the thread. */}
            <div className="@container flex min-h-0 min-w-0 flex-1 flex-col gap-3 @min-[32.5625rem]:flex-row">
                <PlaygroundChatList />
                <PlaygroundThread />
            </div>
        </SceneContent>
    )
}
