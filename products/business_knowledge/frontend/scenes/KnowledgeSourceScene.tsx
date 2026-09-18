import { useActions, useValues } from 'kea'

import { IconBook, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { KnowledgeSourceForm } from '../components/KnowledgeSourceForm'
import { StatusTag } from '../components/StatusTag'
import { REFRESH_INTERVAL_OPTIONS } from './businessKnowledgeLogic'
import { KnowledgeSourceLogicProps, knowledgeSourceLogic } from './knowledgeSourceLogic'

export const scene: SceneExport<KnowledgeSourceLogicProps> = {
    component: KnowledgeSourceScene,
    logic: knowledgeSourceLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function KnowledgeSourceScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const {
        source,
        sourceLoading,
        sourceNotFound,
        isSourceTextReady,
        isEditSourceSubmitting,
        isEditUrlSourceSubmitting,
        isRefreshing,
        isDeleting,
    } = useValues(knowledgeSourceLogic)
    const { loadSource, submitEditSource, submitEditUrlSource, refreshSource, deleteSource } =
        useActions(knowledgeSourceLogic)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    if (sourceLoading && !source) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-10 w-80 mb-4" />
                <LemonSkeleton className="h-60 max-w-2xl" />
            </SceneContent>
        )
    }

    if (sourceNotFound) {
        return <NotFound object="knowledge source" />
    }

    if (!source) {
        return (
            <SceneContent>
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadSource }}>
                    Couldn't load this knowledge source. Try again.
                </LemonBanner>
            </SceneContent>
        )
    }

    const isUrl = source.source_type === 'url'
    const isSubmitting = isUrl ? isEditUrlSourceSubmitting : isEditSourceSubmitting
    const canRefresh = isUrl && !source.is_generated

    return (
        <SceneContent>
            <SceneTitleSection
                name={source.name}
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBook /> }}
                nameSuffix={
                    <span className="flex items-center gap-1">
                        <LemonTag>{source.source_type}</LemonTag>
                        <StatusTag source={source} />
                    </span>
                }
                actions={
                    <div className="flex gap-2 flex-wrap">
                        <LemonButton
                            type="primary"
                            loading={isSubmitting}
                            disabledReason={!isSourceTextReady ? 'Loading source content' : undefined}
                            onClick={isUrl ? submitEditUrlSource : submitEditSource}
                            // pinned: autocapture / Playwright key. Do not rename.
                            data-attr="business-knowledge-source-save"
                        >
                            Save
                        </LemonButton>
                        {canRefresh && (
                            <LemonButton
                                icon={<IconRefresh />}
                                loading={isRefreshing}
                                disabledReason={isDeleting ? 'Deleting this source' : undefined}
                                onClick={() => refreshSource()}
                                // pinned: autocapture / Playwright key. Do not rename.
                                data-attr="business-knowledge-source-refresh"
                            >
                                Refresh
                            </LemonButton>
                        )}
                        <LemonButton
                            icon={<IconTrash />}
                            status="danger"
                            loading={isDeleting}
                            onClick={() => {
                                LemonDialog.open({
                                    title: `Delete "${source.name}"?`,
                                    description: 'Chunks will be removed.',
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        onClick: () => deleteSource(),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                            // pinned: autocapture / Playwright key. Do not rename.
                            data-attr="business-knowledge-source-delete"
                        >
                            Delete
                        </LemonButton>
                    </div>
                }
            />
            <KnowledgeSourceForm refreshIntervalOptions={REFRESH_INTERVAL_OPTIONS} />
        </SceneContent>
    )
}
