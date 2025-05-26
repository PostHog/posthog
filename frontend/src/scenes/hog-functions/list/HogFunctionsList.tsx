import { LemonCheckbox, LemonInput, LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { HogFunctionMetricSparkLine } from 'scenes/hog-functions/metrics/HogFunctionMetricsSparkline'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

import { HogFunctionIcon } from '../configuration/HogFunctionIcon'
import { humanizeHogFunctionType } from '../hog-function-utils'
import { hogFunctionListLogic, HogFunctionListLogicProps } from './hogFunctionListLogic'
import { hogFunctionRequestModalLogic } from './hogFunctionRequestModalLogic'

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
                            render: function RenderStatus(_, hogFunction) {
                                return (
                                    <>
                                        {hogFunction.enabled ? (
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
                            render: function Render(_, hogFunction) {
                                return (
                                    <More
                                        overlay={
                                            <LemonMenuOverlay
                                                items={[
                                                    {
                                                        label: hogFunction.enabled ? 'Pause' : 'Unpause',
                                                        onClick: () => toggleEnabled(hogFunction, !hogFunction.enabled),
                                                        disabledReason:
                                                            !canEnableHogFunction(hogFunction) && !hogFunction.enabled
                                                                ? `Data pipelines add-on is required for enabling new ${humanizedType}`
                                                                : undefined,
                                                    },
                                                    {
                                                        label: 'Delete',
                                                        status: 'danger' as const, // for typechecker happiness
                                                        onClick: () => deleteHogFunction(hogFunction),
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
                                No {humanizedType}s matching filters.{' '}
                                <Link onClick={() => resetFilters()}>Clear filters</Link>{' '}
                            </>
                        )
                    }
                    footer={
                        hiddenHogFunctions.length > 0 && (
                            <div className="p-3 text-secondary">
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
