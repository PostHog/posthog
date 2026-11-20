import { useActions, useValues } from 'kea'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgeTabs } from '../../components/BusinessKnowledgeTabs/BusinessKnowledgeTabs'
import { librariesLogic } from './librariesLogic'
import { LibrariesTable } from './LibrariesTable'
import { LibraryCreateModal } from './LibraryCreateModal'

export const scene: SceneExport = {
    component: BusinessKnowledgeLibrariesScene,
    logic: librariesLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
}

export function BusinessKnowledgeLibrariesScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { libraries, librariesLoading } = useValues(librariesLogic)
    const { openCreate, loadLibraries } = useActions(librariesLogic)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files so AI can understand your business context, vision, and policies."
                resourceType={{ type: 'business_knowledge' }}
                actions={
                    // pinned: `business-knowledge-library-new` is an autocapture key. Do not rename.
                    todayRailNav ? (
                        <Button
                            variant="primary"
                            onClick={() => openCreate()}
                            data-attr="business-knowledge-library-new"
                        >
                            <IconPlus />
                            New library
                        </Button>
                    ) : (
                        <LemonButton
                            type="primary"
                            icon={<IconPlusSmall />}
                            onClick={() => openCreate()}
                            data-attr="business-knowledge-library-new"
                        >
                            New library
                        </LemonButton>
                    )
                }
            />
            <BusinessKnowledgeTabs activeTab="libraries" />
            <SceneSection
                title="Libraries"
                description="A library groups sources and repositories. Give an agent a key for one library, and it reads only what is in it."
                className="gap-y-2"
            >
                {!libraries && !librariesLoading ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadLibraries() }}>
                        Couldn't load your libraries. Try again.
                    </LemonBanner>
                ) : (
                    <LibrariesTable />
                )}
            </SceneSection>
            <LibraryCreateModal />
        </SceneContent>
    )
}
