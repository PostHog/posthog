import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import {
    LemonBadge,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { MemberSelect } from 'lib/components/MemberSelect'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'

import { HogFunctionType } from '~/types'

import { HogFunctionIcon } from '../configuration/HogFunctionIcon'
import { humanizeHogFunctionType } from '../hog-function-utils'
import { HogFunctionStatusIndicator } from '../misc/HogFunctionStatusIndicator'
import { HogFunctionOrderModal } from './HogFunctionOrderModal'
import { hogFunctionRequestModalLogic } from './hogFunctionRequestModalLogic'
import { HogFunctionListLogicProps, hogFunctionsListLogic, urlForHogFunction } from './hogFunctionsListLogic'

export function HogFunctionList({
    extraControls,
    hideFeedback = false,
    ...props
}: HogFunctionListLogicProps & { extraControls?: JSX.Element; hideFeedback?: boolean }): JSX.Element {
    const { filteredHogFunctions, filters, loading, pagination, totalCount, currentPage, statusFilter } = useValues(
        hogFunctionsListLogic(props)
    )
    const {
        loadHogFunctions,
        toggleEnabled,
        deleteHogFunction,
        setReorderModalOpen,
        setPagination,
        setSearchValue,
        setStatusFilter,
        setFilters,
    } = useActions(hogFunctionsListLogic(props))

    const { openFeedbackDialog } = useActions(hogFunctionRequestModalLogic)

    const humanizedType = humanizeHogFunctionType(props.type, true)

    useOnMountEffect(() => {
        loadHogFunctions()
    })

    const isManualFunction = useCallback(
        (hogFunction: HogFunctionType): boolean => {
            return props.manualFunctions?.find((f) => f.id === hogFunction.id) !== undefined
        },
        [props.manualFunctions]
    )

    const buildColumns = useMemo((): LemonTableColumn<HogFunctionType, any>[] => {
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
            {
                title: 'Created by',
                width: 0,
                render: (_, hogFunction) => {
                    if (!hogFunction.created_by) {
                        return <span className="text-muted">Unknown</span>
                    }
                    return (
                        <div className="flex items-center gap-2">
                            <ProfilePicture user={hogFunction.created_by} size="sm" />
                            <span>{hogFunction.created_by.first_name || hogFunction.created_by.email}</span>
                        </div>
                    )
                },
            },

            updatedAtColumn() as LemonTableColumn<HogFunctionType, any>,
            {
                title: 'Last 7 days',
                width: 0,
                render: (_, hogFunction) => {
                    if (hogFunction.id.startsWith('batch-export-')) {
                        // TODO: Make this less hacky, maybe with some extended type for managing these values
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
                                                  // TRICKY: Hack for now to just link out to the full view
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
                                                      status: 'danger' as const, // for typechecker happiness
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
            // insert it in the second column
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

    return (
        <div className="flex flex-col gap-4">
            {extraControls && (
                <div className="flex gap-2 items-center">
                    <div className="flex-1" />
                    {extraControls}
                </div>
            )}

            <BindLogic logic={hogFunctionsListLogic} props={props}>
                <div>
                    <h3 className="mb-2">{capitalizeFirstLetter(humanizedType)}</h3>
                    <div className="flex justify-between gap-2 flex-wrap mb-2">
                        <div className="flex items-center gap-2">
                            <LemonInput
                                type="search"
                                placeholder="Search destinations..."
                                value={filters.search || ''}
                                onChange={setSearchValue}
                            />
                            {!hideFeedback && (
                                <>
                                    <LemonDivider vertical />
                                    <Link
                                        className="text-sm font-semibold"
                                        subtle
                                        onClick={() => openFeedbackDialog(props.type)}
                                    >
                                        Can't find what you're looking for?
                                    </Link>
                                </>
                            )}
                        </div>
                        <div className="flex-1" />
                        <div className="flex items-center gap-2">
                            <span>Created by:</span>
                            <MemberSelect
                                value={filters.createdBy || null}
                                onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <span>Status:</span>
                            <LemonSelect
                                value={statusFilter}
                                onChange={setStatusFilter}
                                options={[
                                    { value: 'all', label: 'All functions' },
                                    { value: 'active', label: 'Active' },
                                    { value: 'paused', label: 'Paused' },
                                ]}
                                size="small"
                            />
                        </div>
                    </div>
                    <LemonTable
                        dataSource={filteredHogFunctions}
                        size="small"
                        loading={loading}
                        columns={buildColumns}
                        pagination={{
                            controlled: true,
                            pageSize: pagination.limit,
                            currentPage,
                            entryCount: totalCount,
                        }}
                        defaultSorting={{
                            columnKey: 'updated_at',
                            order: -1,
                        }}
                        onSort={(newSorting) => {
                            const order = newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined
                            setPagination({
                                order,
                                offset: 0,
                            })
                        }}
                        noSortingCancellation
                        emptyState={
                            filteredHogFunctions.length === 0 && !loading ? (
                                <>
                                    No {humanizedType} found.{' '}
                                    {filters.search && <Link onClick={() => setSearchValue('')}>Clear search</Link>}
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
