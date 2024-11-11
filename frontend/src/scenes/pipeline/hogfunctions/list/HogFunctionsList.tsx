import { LemonCheckbox, LemonInput, LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { hogFunctionUrl } from 'scenes/pipeline/hogfunctions/urls'
import { AppMetricSparkLineV2 } from 'scenes/pipeline/metrics/AppMetricsV2Sparkline'
import { urls } from 'scenes/urls'

import { HogFunctionType, PipelineNodeTab, PipelineStage } from '~/types'

import { HogFunctionIcon } from '../HogFunctionIcon'
import { hogFunctionListLogic, HogFunctionListLogicProps } from './hogFunctionListLogic'

export function HogFunctionList({
    extraControls,
    ...props
}: HogFunctionListLogicProps & { extraControls?: JSX.Element }): JSX.Element {
    const { loading, filteredHogFunctions, filters, hogFunctions, canEnableHogFunction } = useValues(
        hogFunctionListLogic(props)
    )
    const { loadHogFunctions, setFilters, resetFilters, toggleEnabled, deleteHogFunction } = useActions(
        hogFunctionListLogic(props)
    )

    useEffect(() => loadHogFunctions(), [])

    return (
        <>
            <div className="flex items-center mb-2 gap-2">
                {!props.forceFilters?.search && (
                    <LemonInput
                        type="search"
                        placeholder="Search..."
                        value={filters.search ?? ''}
                        onChange={(e) => setFilters({ search: e })}
                    />
                )}
                <div className="flex-1" />
                {typeof props.forceFilters?.showPaused !== 'boolean' && (
                    <LemonCheckbox
                        label="Show paused"
                        bordered
                        size="small"
                        checked={filters.showPaused}
                        onChange={(e) => setFilters({ showPaused: e ?? undefined })}
                    />
                )}
                {extraControls}
            </div>

            <BindLogic logic={hogFunctionListLogic} props={props}>
                <LemonTable
                    dataSource={filteredHogFunctions}
                    size="small"
                    loading={loading}
                    columns={[
                        {
                            title: '',
                            width: 0,
                            render: function RenderIcon(_, hogFunction) {
                                return <HogFunctionIcon src={hogFunction.icon_url} size="small" />
                            },
                        },
                        {
                            title: 'Name',
                            sticky: true,
                            sorter: true,
                            key: 'name',
                            dataIndex: 'name',
                            render: (_, hogFunction) => {
                                return (
                                    <LemonTableLink
                                        to={hogFunctionUrl(hogFunction.type, hogFunction.id)}
                                        title={
                                            <>
                                                <Tooltip title="Click to update configuration, view metrics, and more">
                                                    <span>{hogFunction.name}</span>
                                                </Tooltip>
                                            </>
                                        }
                                        description={hogFunction.description}
                                    />
                                )
                            },
                        },

                        {
                            title: 'Last 7 days',
                            render: (_, hogFunction) => {
                                return (
                                    <Link
                                        to={urls.pipelineNode(
                                            // TODO: metrics page for emails
                                            PipelineStage.Destination,
                                            `hog-${hogFunction.id}`,
                                            PipelineNodeTab.Metrics
                                        )}
                                    >
                                        <AppMetricSparkLineV2 id={hogFunction.id} />
                                    </Link>
                                )
                            },
                        },
                        updatedAtColumn() as LemonTableColumn<HogFunctionType, any>,
                        {
                            title: 'Status',
                            key: 'enabled',
                            sorter: (a) => (a.enabled ? 1 : -1),
                            width: 0,
                            render: function RenderStatus(_, destination) {
                                return (
                                    <>
                                        {destination.enabled ? (
                                            <LemonTag type="success" className="uppercase">
                                                Active
                                            </LemonTag>
                                        ) : (
                                            <LemonTag type="default" className="uppercase">
                                                Paused
                                            </LemonTag>
                                        )}
                                    </>
                                )
                            },
                        },
                        {
                            width: 0,
                            render: function Render(_, destination) {
                                return (
                                    <More
                                        overlay={
                                            <LemonMenuOverlay
                                                items={[
                                                    {
                                                        label: destination.enabled ? 'Pause' : 'Unpause',
                                                        onClick: () => toggleEnabled(destination, !destination.enabled),
                                                        disabledReason:
                                                            !canEnableHogFunction(destination) && !destination.enabled
                                                                ? 'Data pipelines add-on is required for enabling new destinations'
                                                                : undefined,
                                                    },
                                                    {
                                                        label: 'Delete',
                                                        status: 'danger' as const, // for typechecker happiness
                                                        onClick: () => deleteHogFunction(destination),
                                                    },
                                                ]}
                                            />
                                        }
                                    />
                                )
                            },
                        },
                    ]}
                    emptyState={
                        hogFunctions.length === 0 && !loading ? (
                            'No destinations found'
                        ) : (
                            <>
                                No destinations matching filters.{' '}
                                <Link onClick={() => resetFilters()}>Clear filters</Link>{' '}
                            </>
                        )
                    }
                />
            </BindLogic>
        </>
    )
}
