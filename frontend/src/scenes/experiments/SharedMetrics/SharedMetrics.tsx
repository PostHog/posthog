import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconPencil } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { pluralize } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'

import { isLegacySharedMetric } from '../utils'
import { SharedMetric } from './sharedMetricLogic'
import { SHARED_METRICS_PER_PAGE, sharedMetricsLogic } from './sharedMetricsLogic'

export const scene: SceneExport = {
    component: SharedMetrics,
    logic: sharedMetricsLogic,
}

export function SharedMetrics(): JSX.Element {
    const { sharedMetrics, sharedMetricsLoading, filters, pagination } = useValues(sharedMetricsLogic)
    const { setSharedMetricsFilters } = useActions(sharedMetricsLogic)

    const page = filters.page || 1
    const count = sharedMetrics.count || 0
    const startCount = count === 0 ? 0 : (page - 1) * SHARED_METRICS_PER_PAGE + 1
    const endCount = page * SHARED_METRICS_PER_PAGE < count ? page * SHARED_METRICS_PER_PAGE : count

    const columns: LemonTableColumns<SharedMetric> = [
        {
            key: 'name',
            title: 'Name',
            render: (_, sharedMetric) => {
                return (
                    <LemonTableLink
                        to={sharedMetric.id ? urls.experimentsSharedMetric(sharedMetric.id) : undefined}
                        title={
                            <>
                                {stringWithWBR(sharedMetric.name, 17)}
                                {isLegacySharedMetric(sharedMetric) && (
                                    <Tooltip
                                        title="This metric uses the legacy engine, so some features and improvements may be missing."
                                        docLink="https://posthog.com/docs/experiments/new-experimentation-engine"
                                    >
                                        <LemonTag type="warning" className="ml-1">
                                            Legacy
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </>
                        }
                    />
                )
            },
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            key: 'description',
            title: 'Description',
            dataIndex: 'description',
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof SharedMetric,
            render: function Render(tags: SharedMetric['tags']) {
                return tags ? <ObjectTags tags={tags} staticOnly /> : null
            },
        } as LemonTableColumn<SharedMetric, keyof SharedMetric | undefined>,
        {
            title: 'Type',
            key: 'type',
            render: (_, metric: SharedMetric) => {
                if (metric.query.kind === NodeKind.ExperimentMetric) {
                    return metric.query.metric_type
                }
                return metric.query.kind === NodeKind.ExperimentTrendsQuery ? 'Trend' : 'Funnel'
            },
        },
        createdByColumn<SharedMetric>() as LemonTableColumn<SharedMetric, keyof SharedMetric | undefined>,
        createdAtColumn<SharedMetric>() as LemonTableColumn<SharedMetric, keyof SharedMetric | undefined>,
        {
            key: 'actions',
            title: 'Actions',
            render: (_, sharedMetric) => {
                return (
                    <div className="flex gap-1">
                        <LemonButton
                            className="max-w-72"
                            type="secondary"
                            size="xsmall"
                            icon={<IconPencil />}
                            onClick={() => {
                                router.actions.push(urls.experimentsSharedMetric(sharedMetric.id))
                            }}
                        />
                        <LemonButton
                            className="max-w-72"
                            type="secondary"
                            size="xsmall"
                            icon={<IconCopy />}
                            onClick={() => {
                                router.actions.push(urls.experimentsSharedMetric(sharedMetric.id, 'duplicate'))
                            }}
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            <LemonBanner type="info">
                Shared metrics let you create reusable metrics that you can quickly add to any experiment. They are
                ideal for tracking key metrics like conversion rates or revenue across different experiments without
                having to set them up each time.
            </LemonBanner>
            <div className="flex justify-between gap-2 flex-wrap items-center">
                <AppShortcut
                    name="SearchSharedMetrics"
                    keybind={[keyBinds.filter]}
                    intent="Search shared metrics"
                    interaction="click"
                    scope={Scene.ExperimentsSharedMetrics}
                >
                    <LemonInput
                        type="search"
                        placeholder="Search shared metrics"
                        onChange={(search) => setSharedMetricsFilters({ search: search || undefined, page: 1 })}
                        value={filters.search || ''}
                        maxLength={200}
                    />
                </AppShortcut>
                <LemonButton size="small" type="primary" to={urls.experimentsSharedMetric('new')}>
                    New shared metric
                </LemonButton>
            </div>
            {count ? (
                <div>
                    <span className="text-secondary">
                        {`${startCount}${endCount > startCount ? '-' + endCount : ''} of ${pluralize(count, 'shared metric')}`}
                    </span>
                </div>
            ) : null}
            <LemonTable
                columns={columns}
                dataSource={sharedMetrics.results || []}
                loading={sharedMetricsLoading}
                emptyState={
                    filters.search ? (
                        <div>No shared metrics found matching "{filters.search}".</div>
                    ) : (
                        <div>You haven't created any shared metrics yet.</div>
                    )
                }
                pagination={pagination}
                nouns={['shared metric', 'shared metrics']}
            />
        </div>
    )
}
