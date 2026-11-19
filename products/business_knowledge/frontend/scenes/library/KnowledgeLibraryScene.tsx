import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconPlus, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { KnowledgeLibraryLogicProps, knowledgeLibraryLogic } from './knowledgeLibraryLogic'
import { LibraryConnectAgentSection } from './LibraryConnectAgentSection'
import { LibraryEditModal } from './LibraryEditModal'
import { LibraryRepositoriesSection } from './LibraryRepositoriesSection'
import { LibrarySourcesSection } from './LibrarySourcesSection'

export const scene: SceneExport<KnowledgeLibraryLogicProps> = {
    component: KnowledgeLibraryScene,
    logic: knowledgeLibraryLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function KnowledgeLibraryScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { library, libraryLoading, libraryNotFound, saving } = useValues(knowledgeLibraryLogic)
    const { loadLibrary, openDialog, deleteLibrary } = useActions(knowledgeLibraryLogic)
    const { push } = useActions(router)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    if (libraryLoading && !library) {
        return (
            <SceneContent>
                <LemonSkeleton className="mb-4 h-10 w-80" />
                <LemonSkeleton className="h-60" />
            </SceneContent>
        )
    }

    if (libraryNotFound) {
        return <NotFound object="library" />
    }

    if (!library) {
        return (
            <SceneContent>
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadLibrary() }}>
                    Couldn't load this library. Try again.
                </LemonBanner>
            </SceneContent>
        )
    }

    // pinned: the Sources tab reads `library` and `new` from this URL.
    const newSourceUrl = combineUrl(urls.businessKnowledge(), { library: library.id }, { new: 1 }).url

    return (
        <SceneContent>
            <SceneTitleSection
                name={library.name}
                resourceType={{ type: 'business_knowledge' }}
                nameSuffix={
                    library.is_default ? (
                        <LemonTag type="highlight" title="Sources learned from support tickets join this library.">
                            Default
                        </LemonTag>
                    ) : null
                }
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            disabledReason={saving ? 'Saving' : undefined}
                            // pinned: autocapture key. Do not rename.
                            data-attr="business-knowledge-library-delete"
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Delete "${library.name}"?`,
                                    description:
                                        'Sources and repositories stay. Only this library is removed. A key for this library stops reading anything.',
                                    primaryButton: {
                                        children: 'Delete library',
                                        status: 'danger',
                                        onClick: () => deleteLibrary(),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        >
                            Delete
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPencil />}
                            onClick={() => openDialog('rename')}
                            // pinned: autocapture key. Do not rename.
                            data-attr="business-knowledge-library-rename"
                        >
                            Rename
                        </LemonButton>
                        {todayRailNav ? (
                            <Button
                                variant="primary"
                                onClick={() => push(newSourceUrl)}
                                data-attr="business-knowledge-library-new-source"
                            >
                                <IconPlus />
                                New source
                            </Button>
                        ) : (
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={<IconPlusSmall />}
                                to={newSourceUrl}
                                data-attr="business-knowledge-library-new-source"
                            >
                                New source
                            </LemonButton>
                        )}
                    </>
                }
            />
            <LibrarySourcesSection />
            <SceneDivider />
            <LibraryRepositoriesSection />
            <SceneDivider />
            <LibraryConnectAgentSection libraryId={library.id} />
            <LibraryEditModal />
        </SceneContent>
    )
}
