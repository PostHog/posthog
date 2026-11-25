import { useActions, useValues } from 'kea'

import { IconMessage, IconSearch } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgeTabs } from '../../components/BusinessKnowledgeTabs/BusinessKnowledgeTabs'
import { businessKnowledgePlaygroundLogic } from './businessKnowledgePlaygroundLogic'
import { PlaygroundChatList } from './PlaygroundChatList'
import { PlaygroundSearch } from './PlaygroundSearch'
import { PlaygroundThread } from './PlaygroundThread'

export const scene: SceneExport = {
    component: BusinessKnowledgePlaygroundScene,
    logic: businessKnowledgePlaygroundLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
}

export function BusinessKnowledgePlaygroundScene(): JSX.Element {
    const { mode } = useValues(businessKnowledgePlaygroundLogic)
    const { setMode } = useActions(businessKnowledgePlaygroundLogic)

    return (
        <SceneContent className="min-h-0 flex-1">
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files so AI can understand your business context, vision, and policies."
                resourceType={{ type: 'business_knowledge' }}
            />
            <BusinessKnowledgeTabs activeTab="playground" />
            <div>
                <LemonSegmentedButton
                    size="small"
                    value={mode}
                    onChange={setMode}
                    options={[
                        {
                            value: 'chat',
                            label: 'Chat',
                            icon: <IconMessage />,
                            // pinned: autocapture / Playwright key. Do not rename.
                            'data-attr': 'business-knowledge-playground-mode-chat',
                        },
                        {
                            value: 'search',
                            label: 'Search',
                            icon: <IconSearch />,
                            // pinned: autocapture / Playwright key. Do not rename.
                            'data-attr': 'business-knowledge-playground-mode-search',
                        },
                    ]}
                />
            </div>
            {mode === 'search' ? (
                <PlaygroundSearch />
            ) : (
                // 521px: a 520px scene stacks the list above the thread.
                <div className="@container flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden @min-[32.5625rem]:flex-row">
                    <PlaygroundChatList />
                    <PlaygroundThread />
                </div>
            )}
        </SceneContent>
    )
}
