import { LemonCheckbox, LemonInput, LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { HogFunctionMetricSparkLine } from 'scenes/hog-functions/metrics/HogFunctionMetricsSparkline'
import { urls } from 'scenes/urls'

import { HogFunctionType, PipelineNodeTab, PipelineStage } from '~/types'

import { HogFunctionIcon } from '../configuration/HogFunctionIcon'
import { hogFunctionListLogic, HogFunctionListLogicProps } from './hogFunctionListLogic'
import { hogFunctionRequestModalLogic } from './hogFunctionRequestModalLogic'
import { humanizeHogFunctionType } from '../hog-function-utils'

export function HogFunctionList({
    extraControls,
    hideFeedback = false,
    ...props
}: HogFunctionListLogicProps & { extraControls?: JSX.Element; hideFeedback?: boolean }): JSX.Element {
    const { loading, filteredHogFunctions, filters, hogFunctions, canEnableHogFunction, hiddenHogFunctions } =
        useValues(hogFunctionListLogic(props))
    const { loadHogFunctions, setFilters, resetFilters, toggleEnabled, deleteHogFunction } = useActions(
        hogFunctionListLogic(props)
    )

    const { openFeedbackDialog } = useActions(hogFunctionRequestModalLogic)

    const humanizedType = humanizeHogFunctionType(props.type)

    useEffect(() => loadHogFunctions(), [])

    return (
        <>
            <div className="flex gap-2 items-center mb-2">
                {!props.forceFilters?.search && (
                    <LemonInput
                        type="search"
                        placeholder="Search..."
                        value={filters.search ?? ''}
                        onChange={(e) => setFilters({ search: e })}
                    />
                )}
                {!hideFeedback ? (
                    <Link className="text-sm font-semibold" subtle onClick={() => openFeedbackDialog(props.type)}>
                        Can't find what you're looking for?
                    </Link>
                ) : null}
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
                                        to={urls.hogFunction(hogFunction.id)}
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

                        updatedAtColumn() as LemonTableColumn<HogFunctionType, any>,
                        {
                            title: 'Last 7 days',
                            width: 0,
                            render: (_, hogFunction) => {
                                return (
                                    <Link to={urls.hogFunction(hogFunction.id) + '?tab=metrics'}>
                                        <HogFunctionMetricSparkLine id={hogFunction.id} />
                                    </Link>
                                )
                            },
                        },
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
                    footer={
                        hiddenHogFunctions.length > 0 && (
                            <div className="text-secondary">
                                {hiddenHogFunctions.length} hidden. <Link onClick={() => resetFilters()}>Show all</Link>
                            </div>
                        )
                    }
                />
            </BindLogic>
            <div className="mb-8" />
        </>
    )
}
