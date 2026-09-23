import { useActions, useValues } from 'kea'

import { IconBook, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { KnowledgeSourceForm } from '../components/KnowledgeSourceForm'
import { StatusTag } from '../components/StatusTag'
import type { KnowledgeSourceDocumentApi, SafetyVerdictEnumApi } from '../generated/api.schemas'
import { REFRESH_INTERVAL_OPTIONS } from './businessKnowledgeLogic'
import { KnowledgeSourceLogicProps, knowledgeSourceLogic } from './knowledgeSourceLogic'

export const scene: SceneExport<KnowledgeSourceLogicProps> = {
    component: KnowledgeSourceScene,
    logic: knowledgeSourceLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function safetyTag(verdict: SafetyVerdictEnumApi): JSX.Element {
    if (verdict === 'safe') {
        return <LemonTag type="success">safe</LemonTag>
    }
    if (verdict === 'unsafe') {
        return (
            <LemonTag type="danger" title="Excluded from search.">
                unsafe
            </LemonTag>
        )
    }
    return (
        <LemonTag type="warning" title="Waiting for the content check. Search skips this page until then.">
            pending
        </LemonTag>
    )
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
        sourceDocuments,
        sourceDocumentsLoaded,
        sourceDocumentsFailed,
    } = useValues(knowledgeSourceLogic)
    const { loadSource, loadSourceDocuments, submitEditSource, submitEditUrlSource, refreshSource, deleteSource } =
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
            {isUrl && (
                <div className="max-w-3xl min-w-0 flex flex-col gap-2">
                    <h3 className="text-sm font-semibold m-0">Indexed pages</h3>
                    {sourceDocumentsFailed && (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: () => loadSourceDocuments() }}
                        >
                            Couldn't load indexed pages.
                        </LemonBanner>
                    )}
                    {!(sourceDocumentsFailed && sourceDocuments.length === 0) && (
                        <LemonTable<KnowledgeSourceDocumentApi>
                            dataSource={sourceDocuments}
                            loading={!sourceDocumentsLoaded}
                            rowKey={(row) => row.id}
                            tableLayout="fixed"
                            nouns={['page', 'pages']}
                            pagination={{ pageSize: 20 }}
                            emptyState={
                                source.status === 'processing'
                                    ? 'Pages show up here after indexing finishes.'
                                    : 'No pages indexed.'
                            }
                            columns={[
                                {
                                    title: 'URL',
                                    key: 'url',
                                    width: '55%',
                                    render: (_, row) =>
                                        row.url ? (
                                            <Link
                                                to={row.url}
                                                target="_blank"
                                                title={row.url}
                                                className="block max-w-full truncate"
                                            >
                                                {row.url}
                                            </Link>
                                        ) : (
                                            <span className="text-muted">No URL</span>
                                        ),
                                },
                                {
                                    title: 'Title',
                                    key: 'title',
                                    width: '30%',
                                    render: (_, row) => (
                                        <span className="block max-w-full truncate" title={row.title || undefined}>
                                            {row.title}
                                        </span>
                                    ),
                                },
                                {
                                    title: 'Content check',
                                    key: 'safety_verdict',
                                    width: '15%',
                                    render: (_, row) => safetyTag(row.safety_verdict),
                                },
                            ]}
                        />
                    )}
                </div>
            )}
        </SceneContent>
    )
}
