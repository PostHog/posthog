import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInputSelect, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { StatusTag } from '../../components/StatusTag/StatusTag'
import type { KnowledgeSourceApi } from '../../generated/api.schemas'
import { KnowledgeSourceNameCell } from '../sources/KnowledgeSourceNameCell'
import { knowledgeLibraryLogic } from './knowledgeLibraryLogic'

export function LibrarySourcesSection(): JSX.Element {
    const { sources, sourcesLoading, addableSources, projectSourcesLoading, projectSourcesFailed, changingSourceIds } =
        useValues(knowledgeLibraryLogic)
    const { addSource, removeSource, loadSources, loadProjectSources } = useActions(knowledgeLibraryLogic)

    return (
        <SceneSection
            title="Sources"
            description="An agent with a key for this library searches only these sources."
            className="gap-y-2"
        >
            <div className="max-w-100">
                <LemonInputSelect
                    mode="single"
                    value={[]}
                    options={addableSources.map((source) => ({ key: source.id, label: source.name }))}
                    onChange={([sourceId]) => sourceId && addSource(sourceId)}
                    onInputChange={loadProjectSources}
                    disableFiltering
                    emptyStateComponent={<span className="p-2 text-secondary">No other sources match.</span>}
                    loading={projectSourcesLoading || changingSourceIds.length > 0}
                    disabled={changingSourceIds.length > 0}
                    placeholder="Add an existing source"
                    data-attr="business-knowledge-library-add-source"
                />
            </div>
            {projectSourcesFailed && (
                <p className="m-0 text-secondary">
                    Couldn't load the sources you can add.{' '}
                    <Link onClick={() => loadProjectSources(undefined)}>Try again</Link>
                </p>
            )}
            {!sources && !sourcesLoading ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadSources() }}>
                    Couldn't load the sources in this library. Try again.
                </LemonBanner>
            ) : (
                <LemonTable<KnowledgeSourceApi>
                    dataSource={sources ?? []}
                    loading={sourcesLoading}
                    rowKey="id"
                    pagination={{ pageSize: 20 }}
                    nouns={['source', 'sources']}
                    emptyState="This library has no sources yet. Add an existing source, or create a new one."
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, source) => <KnowledgeSourceNameCell source={source} />,
                        },
                        {
                            title: 'Type',
                            key: 'source_type',
                            render: (_, source) => <LemonTag>{source.source_type}</LemonTag>,
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, source) => <StatusTag source={source} />,
                        },
                        {
                            title: 'Chunks',
                            key: 'chunk_count',
                            render: (_, source) => source.chunk_count.toLocaleString(),
                        },
                        {
                            title: '',
                            key: 'actions',
                            width: 0,
                            render: (_, source) => (
                                <LemonButton
                                    icon={<IconX />}
                                    size="small"
                                    tooltip="Remove from this library. The source stays in your business knowledge."
                                    loading={changingSourceIds.includes(source.id)}
                                    onClick={() => removeSource(source.id)}
                                    data-attr="business-knowledge-library-remove-source"
                                />
                            ),
                        },
                    ]}
                />
            )}
        </SceneSection>
    )
}
