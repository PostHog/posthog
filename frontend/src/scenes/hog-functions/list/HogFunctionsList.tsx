import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { LemonBadge, LemonButton, LemonInput, LemonTable, LemonTableColumn, Link, Tooltip } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

import { HogFunctionIcon } from '../configuration/HogFunctionIcon'
import { humanizeHogFunctionType } from '../hog-function-utils'
import { HogFunctionStatusIndicator } from '../misc/HogFunctionStatusIndicator'
import { HogFunctionOrderModal } from './HogFunctionOrderModal'
import { hogFunctionRequestModalLogic } from './hogFunctionRequestModalLogic'
import { HogFunctionListLogicProps, hogFunctionsListLogic } from './hogFunctionsListLogic'

const urlForHogFunction = (hogFunction: HogFunctionType): string => {
    if (hogFunction.id.startsWith('plugin-')) {
        return urls.legacyPlugin(hogFunction.id.replace('plugin-', ''))
    }
    if (hogFunction.id.startsWith('batch-export-')) {
        return urls.batchExport(hogFunction.id.replace('batch-export-', ''))
    }
    return urls.hogFunction(hogFunction.id)
}

export function HogFunctionList({
    extraControls,
    hideFeedback = false,
    ...props
}: HogFunctionListLogicProps & { extraControls?: JSX.Element; hideFeedback?: boolean }): JSX.Element {
    const {
        filteredActiveHogFunctions,
        filteredPausedHogFunctions,
        filters,
        activeLoading,
        pausedLoading,
        activePagination,
        pausedPagination,
        activeTotalCount,
        pausedTotalCount,
    } = useValues(hogFunctionsListLogic(props))
    const {
        loadActiveHogFunctions,
        loadPausedHogFunctions,
        setFilters,
        resetFilters,
        toggleEnabled,
        deleteHogFunction,
        setReorderModalOpen,
        setPagination,
    } = useActions(hogFunctionsListLogic(props))

    const { openFeedbackDialog } = useActions(hogFunctionRequestModalLogic)

    const humanizedType = humanizeHogFunctionType(props.type)

    useOnMountEffect(() => {
        loadActiveHogFunctions()
        loadPausedHogFunctions()
    })

    const isManualFunction = useCallback(
        (hogFunction: HogFunctionType): boolean => {
            return props.manualFunctions?.find((f) => f.id === hogFunction.id) !== undefined
        },
        [props.manualFunctions]
    )

    const buildColumns = useCallback((): LemonTableColumn<HogFunctionType, any>[] => {
        const columns: LemonTableColumn<HogFunctionType, any>[] = [
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
                            to={urlForHogFunction(hogFunction)}
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
                    if (hogFunction.id.startsWith('batch-export-')) {
                        const batchExportId = hogFunction.id.replace('batch-export-', '')
                        return (
                            <Link to={urlForHogFunction(hogFunction) + '?tab=metrics'}>
                                <AppMetricsSparkline
                                    logicKey={batchExportId}
                                    forceParams={{
                                        appSource: 'batch_export',
                                        appSourceId: batchExportId,
                                        metricKind: ['success', 'failure'],
                                        breakdownBy: 'metric_kind',
                                        interval: 'day',
                                        dateFrom: '-7d',
                                    }}
                                />
                            </Link>
                        )
                    }

                    if (isManualFunction(hogFunction) || hogFunction.type === 'site_app') {
                        return <>N/A</>
                    }

                    return (
                        <Link to={urlForHogFunction(hogFunction) + '?tab=metrics'}>
                            <AppMetricsSparkline
                                logicKey={hogFunction.id}
                                forceParams={{
                                    appSource: 'hog_function',
                                    appSourceId: hogFunction.id,
                                    metricKind: ['success', 'failure'],
                                    breakdownBy: 'metric_kind',
                                    interval: 'day',
                                    dateFrom: '-7d',
                                }}
                            />
                        </Link>
                    )
                },
            },
            {
                title: 'Status',
                key: 'enabled',
                sorter: (a) => (a.enabled ? 1 : -1),
                width: 0,
                render: function RenderStatus(_, hogFunction) {
                    return <HogFunctionStatusIndicator hogFunction={hogFunction} />
                },
            },
            {
                width: 0,
                render: function Render(_, hogFunction) {
                    return (
                        <More
                            overlay={
                                <LemonMenuOverlay
                                    items={
                                        isManualFunction(hogFunction)
                                            ? [
                                                  {
                                                      label: 'View & configure',
                                                      to: urlForHogFunction(hogFunction),
                                                  },
                                              ]
                                            : [
                                                  {
                                                      label: hogFunction.enabled ? 'Pause' : 'Unpause',
                                                      onClick: () => toggleEnabled(hogFunction, !hogFunction.enabled),
                                                  },
                                                  {
                                                      label: 'Delete',
                                                      status: 'danger' as const,
                                                      onClick: () => deleteHogFunction(hogFunction),
                                                  },
                                              ]
                                    }
                                />
                            }
                        />
                    )
                },
            },
        ]

        if (props.type === 'transformation') {
            columns.splice(1, 0, {
                title: 'Prio',
                key: 'execution_order',
                sorter: (a) => (a.execution_order ? 1 : -1),
                width: 0,
                render: function Render(_, hogFunction) {
                    return (
                        <LemonButton
                            size="small"
                            tooltip="Transformations are executed in a specific order. Click to reorder them."
                            onClick={() => setReorderModalOpen(true)}
                        >
                            <LemonBadge.Number count={hogFunction.execution_order ?? 0} status="muted" />
                        </LemonButton>
                    )
                },
            })
        }

        return columns
    }, [props.type, toggleEnabled, deleteHogFunction, isManualFunction, setReorderModalOpen])

    const activeColumns = useMemo(() => buildColumns(), [buildColumns])
    const pausedColumns = useMemo(() => buildColumns(), [buildColumns])

    return (
        <div className="flex flex-col gap-4">
            <div className="flex gap-2 items-center">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    value={filters.search ?? ''}
                    onChange={(e) => setFilters({ search: e })}
                />
                {!hideFeedback ? (
                    <Link className="text-sm font-semibold" subtle onClick={() => openFeedbackDialog(props.type)}>
                        Can't find what you're looking for?
                    </Link>
                ) : null}
                <div className="flex-1" />
                {extraControls}
            </div>

            <BindLogic logic={hogFunctionsListLogic} props={props}>
                {/* Active Functions Table */}
                <div>
                    <h3 className="mb-2">Active {humanizedType}s</h3>
                    <LemonTable
                        dataSource={filteredActiveHogFunctions}
                        size="small"
                        loading={activeLoading}
                        columns={activeColumns}
                        pagination={{
                            controlled: true,
                            pageSize: activePagination.limit,
                            currentPage: Math.floor(activePagination.offset / activePagination.limit) + 1,
                            entryCount: activeTotalCount,
                            onForward:
                                activePagination.offset + activePagination.limit < activeTotalCount
                                    ? () =>
                                          setPagination('active', {
                                              offset: activePagination.offset + activePagination.limit,
                                          })
                                    : undefined,
                            onBackward:
                                activePagination.offset > 0
                                    ? () =>
                                          setPagination('active', {
                                              offset: Math.max(0, activePagination.offset - activePagination.limit),
                                          })
                                    : undefined,
                        }}
                        emptyState={
                            filteredActiveHogFunctions.length === 0 && !activeLoading ? (
                                <>
                                    No active {humanizedType}s found.{' '}
                                    {filters.search && <Link onClick={() => resetFilters()}>Clear filters</Link>}
                                </>
                            ) : undefined
                        }
                    />
                </div>

                {/* Paused Functions Table */}
                <div>
                    <h3 className="mb-2">Paused {humanizedType}s</h3>
                    <LemonTable
                        dataSource={filteredPausedHogFunctions}
                        size="small"
                        loading={pausedLoading}
                        columns={pausedColumns}
                        pagination={{
                            controlled: true,
                            pageSize: pausedPagination.limit,
                            currentPage: Math.floor(pausedPagination.offset / pausedPagination.limit) + 1,
                            entryCount: pausedTotalCount,
                            onForward:
                                pausedPagination.offset + pausedPagination.limit < pausedTotalCount
                                    ? () =>
                                          setPagination('paused', {
                                              offset: pausedPagination.offset + pausedPagination.limit,
                                          })
                                    : undefined,
                            onBackward:
                                pausedPagination.offset > 0
                                    ? () =>
                                          setPagination('paused', {
                                              offset: Math.max(0, pausedPagination.offset - pausedPagination.limit),
                                          })
                                    : undefined,
                        }}
                        emptyState={
                            filteredPausedHogFunctions.length === 0 && !pausedLoading ? (
                                <>
                                    No paused {humanizedType}s found.{' '}
                                    {filters.search && <Link onClick={() => resetFilters()}>Clear filters</Link>}
                                </>
                            ) : undefined
                        }
                    />
                </div>

                <HogFunctionOrderModal />
            </BindLogic>
        </div>
    )
}
