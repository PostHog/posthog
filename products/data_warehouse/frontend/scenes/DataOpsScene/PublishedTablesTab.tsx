import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { PublishedTableApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { publishedTablesLogic } from './publishedTablesLogic'
import { PublishTableModal } from './PublishTableModal'

const ACTIVE_STATUSES = new Set<PublishedTableApi['status']>(['pending', 'publishing'])

export function PublicationStatus({ publication }: { publication: PublishedTableApi }): JSX.Element {
    if (publication.status === 'failed') {
        const tag = <LemonTag type="danger">Failed</LemonTag>
        return publication.last_error ? (
            <Tooltip title={publication.last_error} interactive>
                {tag}
            </Tooltip>
        ) : (
            tag
        )
    }
    if (publication.status === 'completed') {
        return <LemonTag type="success">Published</LemonTag>
    }
    if (publication.status === 'publishing') {
        return <LemonTag type="primary">Publishing</LemonTag>
    }
    return <LemonTag type="muted">Queued</LemonTag>
}

export function PublishedTablesTab(): JSX.Element {
    const {
        activeMutationId,
        filteredPublishedTables,
        publishedTables,
        publishedTablesError,
        publishedTablesLoading,
        republishedTableLoading,
        searchTerm,
        unpublishedTableIdLoading,
    } = useValues(publishedTablesLogic)
    const { loadPublishedTables, openPublishModal, republishTable, setSearchTerm, unpublishTable } =
        useActions(publishedTablesLogic)
    const mutationLoading = republishedTableLoading || unpublishedTableIdLoading

    return (
        <div className="py-4">
            <PublishTableModal />
            <SceneSection
                title="Published tables"
                description="Publish snapshots of modeled tables so you can query them with other warehouse data in PostHog."
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            onClick={() => loadPublishedTables()}
                            loading={publishedTablesLoading}
                            data-attr="refresh-published-tables"
                        >
                            Refresh
                        </LemonButton>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.WarehouseObjects}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={openPublishModal}
                                data-attr="open-publish-table"
                            >
                                Publish table
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            >
                <div className="flex flex-col gap-4">
                    {(!!publishedTables?.length || !!searchTerm) && !publishedTablesError ? (
                        <LemonInput
                            type="search"
                            placeholder="Search published tables"
                            value={searchTerm}
                            onChange={setSearchTerm}
                            className="max-w-80"
                        />
                    ) : null}

                    {publishedTablesError ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: () => loadPublishedTables() }}
                        >
                            {publishedTablesError}
                        </LemonBanner>
                    ) : (
                        <LemonTable
                            dataSource={filteredPublishedTables}
                            loading={publishedTablesLoading || publishedTables === null}
                            nouns={['published table', 'published tables']}
                            emptyState={
                                searchTerm
                                    ? 'No published tables match your search.'
                                    : 'No tables have been published yet. Publish a modeled table to get started.'
                            }
                            columns={[
                                {
                                    title: 'Table in PostHog',
                                    key: 'name',
                                    render: (_, publication: PublishedTableApi) =>
                                        publication.status === 'completed' ? (
                                            <Link
                                                to={urls.sqlEditor({
                                                    query: `SELECT * FROM ${publication.name} LIMIT 100`,
                                                })}
                                            >
                                                <strong>{publication.name}</strong>
                                            </Link>
                                        ) : (
                                            <strong>{publication.name}</strong>
                                        ),
                                },
                                {
                                    title: 'Modeled table',
                                    key: 'source',
                                    render: (_, publication: PublishedTableApi) => (
                                        <code>
                                            {publication.source_schema_name}.{publication.source_table_name}
                                        </code>
                                    ),
                                },
                                {
                                    title: 'Status',
                                    key: 'status',
                                    render: (_, publication: PublishedTableApi) => (
                                        <PublicationStatus publication={publication} />
                                    ),
                                },
                                {
                                    title: 'Rows',
                                    key: 'row_count',
                                    align: 'right',
                                    render: (_, publication: PublishedTableApi) =>
                                        publication.row_count === null ? '—' : publication.row_count.toLocaleString(),
                                },
                                {
                                    title: 'Last published',
                                    key: 'last_published_at',
                                    render: (_, publication: PublishedTableApi) =>
                                        publication.last_published_at ? (
                                            <TZLabel time={publication.last_published_at} />
                                        ) : (
                                            'Never'
                                        ),
                                },
                                {
                                    key: 'actions',
                                    width: 0,
                                    render: (_, publication: PublishedTableApi) => {
                                        const publicationActive = ACTIVE_STATUSES.has(publication.status)
                                        const thisPublicationLoading =
                                            activeMutationId === publication.id && mutationLoading

                                        return (
                                            <More
                                                overlay={
                                                    <>
                                                        <AccessControlAction
                                                            resourceType={AccessControlResourceType.WarehouseObjects}
                                                            minAccessLevel={AccessControlLevel.Editor}
                                                        >
                                                            <LemonButton
                                                                onClick={() => republishTable(publication.id)}
                                                                loading={
                                                                    thisPublicationLoading && republishedTableLoading
                                                                }
                                                                data-attr={`republish-table-${publication.id}`}
                                                                disabledReason={
                                                                    publicationActive
                                                                        ? 'This table is already being published'
                                                                        : mutationLoading
                                                                          ? 'Another table update is in progress'
                                                                          : undefined
                                                                }
                                                            >
                                                                {publication.status === 'failed'
                                                                    ? 'Try publishing again'
                                                                    : 'Publish again'}
                                                            </LemonButton>
                                                        </AccessControlAction>
                                                        <AccessControlAction
                                                            resourceType={AccessControlResourceType.WarehouseObjects}
                                                            minAccessLevel={AccessControlLevel.Editor}
                                                        >
                                                            <LemonButton
                                                                status="danger"
                                                                loading={
                                                                    thisPublicationLoading && unpublishedTableIdLoading
                                                                }
                                                                data-attr={`unpublish-table-${publication.id}`}
                                                                disabledReason={
                                                                    publicationActive
                                                                        ? 'Wait for publishing to finish before unpublishing'
                                                                        : mutationLoading
                                                                          ? 'Another table update is in progress'
                                                                          : undefined
                                                                }
                                                                onClick={() =>
                                                                    LemonDialog.open({
                                                                        title: `Unpublish ${publication.name}?`,
                                                                        description:
                                                                            'This removes the table and its published snapshot from PostHog. The modeled table is not changed.',
                                                                        primaryButton: {
                                                                            status: 'danger',
                                                                            children: 'Unpublish table',
                                                                            onClick: () =>
                                                                                unpublishTable(publication.id),
                                                                        },
                                                                        secondaryButton: { children: 'Cancel' },
                                                                    })
                                                                }
                                                            >
                                                                Unpublish
                                                            </LemonButton>
                                                        </AccessControlAction>
                                                    </>
                                                }
                                            />
                                        )
                                    },
                                },
                            ]}
                        />
                    )}
                </div>
            </SceneSection>
        </div>
    )
}
