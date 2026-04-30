import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import { NodeKind } from '~/queries/schema/schema-general'

import { isLegacySharedMetric, matchesSharedMetricSearch } from '../utils'
import { InlineTagEditor } from './InlineTagEditor'
import { SharedMetric } from './sharedMetricLogic'
import { sharedMetricsLogic } from './sharedMetricsLogic'

export const scene: SceneExport = {
    component: SharedMetrics,
    logic: sharedMetricsLogic,
}

export function SharedMetrics(): JSX.Element {
    const { sharedMetrics, sharedMetricsLoading, searchTerm, savingTagsMetricId } = useValues(sharedMetricsLogic)
    const { setSearchTerm, updateSharedMetricTags, deleteSharedMetric } = useActions(sharedMetricsLogic)
    const { tags: allTags } = useValues(tagsModel)

    const searchLower = searchTerm.toLowerCase()
    const filteredMetrics = searchTerm
        ? (sharedMetrics || []).filter((metric) => matchesSharedMetricSearch(metric, searchLower))
        : sharedMetrics || []

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
            render: function Render(_: any, metric: SharedMetric) {
                return (
                    <InlineTagEditor
                        metric={metric}
                        allTags={allTags}
                        onSave={(newTags) => updateSharedMetricTags(metric.id, newTags)}
                        saving={savingTagsMetricId === metric.id}
                    />
                )
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
            title: '',
            width: 0,
            render: (_, sharedMetric) => {
                return (
                    <More
                        size="xsmall"
                        overlay={
                            <>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    icon={<IconPencil />}
                                    onClick={() => {
                                        router.actions.push(urls.experimentsSharedMetric(sharedMetric.id))
                                    }}
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    icon={<IconCopy />}
                                    onClick={() => {
                                        router.actions.push(urls.experimentsSharedMetric(sharedMetric.id, 'duplicate'))
                                    }}
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    icon={<IconTrash />}
                                    status="danger"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete this metric?',
                                            content: (
                                                <div className="text-sm text-secondary">
                                                    This action cannot be undone.
                                                </div>
                                            ),
                                            primaryButton: {
                                                children: 'Delete',
                                                type: 'primary',
                                                onClick: () => deleteSharedMetric(sharedMetric.id),
                                                size: 'small',
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                                type: 'tertiary',
                                                size: 'small',
                                            },
                                        })
                                    }}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
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
            <div className="flex justify-between items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search shared metrics..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                />
                <LemonButton size="small" type="primary" to={urls.experimentsSharedMetric('new')}>
                    New shared metric
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={filteredMetrics}
                loading={sharedMetricsLoading}
                emptyState={<div>You haven't created any shared metrics yet.</div>}
            />
        </div>
    )
}
