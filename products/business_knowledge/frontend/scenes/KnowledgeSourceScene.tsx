import { useActions, useValues } from 'kea'

import { IconBook } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { KnowledgeSourceDetails } from '../components/KnowledgeSourceDetails'
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
        editSourceChanged,
        editUrlSourceChanged,
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
                <LemonSkeleton className="mb-4 h-10 w-80" />
                <div className="flex flex-col gap-4 @min-[48rem]/main-content:flex-row">
                    <LemonSkeleton className="h-60 min-w-0 flex-1" />
                    <LemonSkeleton className="h-48 @min-[48rem]/main-content:w-80" />
                </div>
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
    const hasChanges = isUrl ? editUrlSourceChanged : editSourceChanged

    return (
        <SceneContent>
            <SceneTitleSection
                name={source.name}
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBook /> }}
                nameSuffix={<StatusTag source={source} />}
            />
            {source.status === 'error' && source.error_message ? (
                <LemonBanner type="error">{source.error_message}</LemonBanner>
            ) : null}
            {source.has_unsafe_documents ? (
                <LemonBanner type="warning">
                    Some pages were flagged and are excluded from search. They stay listed below.
                </LemonBanner>
            ) : null}
            <div className="flex flex-col gap-4 @min-[48rem]/main-content:flex-row @min-[48rem]/main-content:items-start">
                <div className="flex min-w-0 flex-1 flex-col gap-4">
                    <LemonCard hoverEffect={false} className="px-4 py-3">
                        <KnowledgeSourceForm refreshIntervalOptions={REFRESH_INTERVAL_OPTIONS} />
                        <div className="mt-3 flex justify-end border-t pt-3">
                            <LemonButton
                                type="primary"
                                size="small"
                                loading={isSubmitting}
                                disabledReason={
                                    !isSourceTextReady
                                        ? 'Loading source content'
                                        : !hasChanges
                                          ? 'No changes to save'
                                          : undefined
                                }
                                onClick={isUrl ? submitEditUrlSource : submitEditSource}
                                // pinned: autocapture / Playwright key. Do not rename.
                                data-attr="business-knowledge-source-save"
                            >
                                Save
                            </LemonButton>
                        </div>
                    </LemonCard>
                    {isUrl ? (
                        <LemonCard hoverEffect={false} className="px-4 py-3">
                            <h3 className="mb-2 text-sm font-semibold">Indexed pages</h3>
                            {sourceDocumentsFailed ? (
                                <LemonBanner
                                    type="error"
                                    className="mb-2"
                                    action={{ children: 'Try again', onClick: () => loadSourceDocuments() }}
                                >
                                    Couldn't load indexed pages.
                                </LemonBanner>
                            ) : null}
                            {!(sourceDocumentsFailed && sourceDocuments.length === 0) ? (
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
                                                <span
                                                    className="block max-w-full truncate"
                                                    title={row.title || undefined}
                                                >
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
                            ) : null}
                        </LemonCard>
                    ) : null}
                </div>
                <div className="min-w-0 @min-[48rem]/main-content:w-80 @min-[48rem]/main-content:shrink-0">
                    <KnowledgeSourceDetails
                        source={source}
                        isRefreshing={isRefreshing}
                        isDeleting={isDeleting}
                        onRefresh={() => refreshSource()}
                        onDelete={() => deleteSource()}
                    />
                </div>
            </div>
        </SceneContent>
    )
}
