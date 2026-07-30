import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { PublishedTableApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { publishedTablesLogic } from './publishedTablesLogic'
import { PublishTableModal } from './PublishTableModal'

const ACTIVE_STATUSES = new Set<PublishedTableApi['status']>(['pending', 'publishing'])

function PublicationStatus({ publication }: { publication: PublishedTableApi }): JSX.Element {
    if (publication.status === 'failed') {
        return publication.last_error ? (
            <Tooltip title={publication.last_error} interactive>
                <LemonTag type="danger">Failed</LemonTag>
            </Tooltip>
        ) : (
            <LemonTag type="danger">Failed</LemonTag>
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
        filteredPublishedTables,
        publishedTables,
        publishedTablesError,
        publishedTablesLoading,
        searchTerm,
        republishedTableLoading,
        unpublishedTableIdLoading,
    } = useValues(publishedTablesLogic)
    const { loadPublishedTables, openPublishModal, republishTable, setSearchTerm, unpublishTable } =
        useActions(publishedTablesLogic)
    const mutationLoading = republishedTableLoading || unpublishedTableIdLoading

    return (
        <div className="space-y-4 py-4">
            <PublishTableModal />
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 className="text-lg font-semibold mb-1">Published tables</h2>
                    <p className="text-muted m-0">
                        Publish snapshots of modeled tables so they can be queried alongside other warehouse data.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={() => loadPublishedTables()}
                        loading={publishedTablesLoading}
                    >
                        Refresh
                    </LemonButton>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.WarehouseObjects}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton type="primary" icon={<IconPlus />} onClick={openPublishModal}>
                            Publish table
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

            {publishedTables.length > 0 || searchTerm ? (
                <LemonInput
                    type="search"
                    placeholder="Search published tables"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="max-w-80"
                />
            ) : null}

            {publishedTablesError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadPublishedTables() }}>
                    {publishedTablesError}
                </LemonBanner>
            ) : null}

            <LemonTable
                dataSource={filteredPublishedTables}
                loading={publishedTablesLoading}
                nouns={['published table', 'published tables']}
                emptyState={searchTerm ? 'No published tables match your search' : 'No published tables'}
                columns={[
                    {
                        title: 'Warehouse table',
                        key: 'name',
                        render: (_, publication: PublishedTableApi) =>
                            publication.table_id ? (
                                <Link to={urls.sqlEditor({ query: `SELECT * FROM ${publication.name} LIMIT 100` })}>
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
                        render: (_, publication: PublishedTableApi) => <PublicationStatus publication={publication} />,
                    },
                    {
                        title: 'Rows',
                        key: 'row_count',
                        align: 'right',
                        render: (_, publication: PublishedTableApi) =>
                            publication.row_count === null ? '-' : publication.row_count.toLocaleString(),
                    },
                    {
                        title: 'Last published',
                        key: 'last_published_at',
                        render: (_, publication: PublishedTableApi) =>
                            publication.last_published_at ? <TZLabel time={publication.last_published_at} /> : 'Never',
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, publication: PublishedTableApi) => {
                            const isActive = ACTIVE_STATUSES.has(publication.status)
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
                                                    loading={republishedTableLoading}
                                                    disabledReason={
                                                        isActive
                                                            ? 'This table is already being published'
                                                            : mutationLoading
                                                              ? 'Another table update is in progress'
                                                              : undefined
                                                    }
                                                >
                                                    {publication.status === 'failed' ? 'Try again' : 'Publish again'}
                                                </LemonButton>
                                            </AccessControlAction>
                                            <AccessControlAction
                                                resourceType={AccessControlResourceType.WarehouseObjects}
                                                minAccessLevel={AccessControlLevel.Editor}
                                            >
                                                <LemonButton
                                                    status="danger"
                                                    loading={unpublishedTableIdLoading}
                                                    disabledReason={
                                                        isActive
                                                            ? 'Wait for publishing to finish before unpublishing'
                                                            : mutationLoading
                                                              ? 'Another table update is in progress'
                                                              : undefined
                                                    }
                                                    onClick={() =>
                                                        LemonDialog.open({
                                                            title: `Unpublish ${publication.name}?`,
                                                            description:
                                                                'This removes the table from PostHog and deletes its published snapshot. The modeled table is not changed.',
                                                            primaryButton: {
                                                                status: 'danger',
                                                                children: 'Unpublish table',
                                                                onClick: () => unpublishTable(publication.id),
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
            {!publishedTablesLoading && publishedTables.length === 0 ? (
                <p className="text-muted text-center -mt-2">Publish a modeled table to query it from PostHog.</p>
            ) : null}
        </div>
    )
}
