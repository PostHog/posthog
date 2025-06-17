import {
    LemonBadge,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonTable,
    LemonTableColumn,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useCallback, useEffect, useMemo } from 'react'
import { HogFunctionMetricSparkLine } from 'scenes/hog-functions/metrics/HogFunctionMetricsSparkline'
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
    const { loading, filteredHogFunctions, filters, hogFunctions, canEnableHogFunction, hiddenHogFunctions } =
        useValues(hogFunctionsListLogic(props))
    const { loadHogFunctions, setFilters, resetFilters, toggleEnabled, deleteHogFunction, setReorderModalOpen } =
        useActions(hogFunctionsListLogic(props))

    const { openFeedbackDialog } = useActions(hogFunctionRequestModalLogic)

    const humanizedType = humanizeHogFunctionType(props.type)

    useEffect(() => loadHogFunctions(), [])

    const isManualFunction = useCallback(
        (hogFunction: HogFunctionType): boolean => {
            return props.manualFunctions?.find((f) => f.id === hogFunction.id) !== undefined
        },
        [props.manualFunctions]
    )

    const columns = useMemo(() => {
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
                    if (isManualFunction(hogFunction) || hogFunction.type === 'site_app') {
                        return <>N/A</>
                    }
                    return (
                        <Link to={urlForHogFunction(hogFunction) + '?tab=metrics'}>
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
    }, [props.type, canEnableHogFunction, humanizedType, toggleEnabled, deleteHogFunction, isManualFunction])

    return (
        <>
            <div className="flex gap-2 items-center mb-2">
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
                <LemonCheckbox
                    label="Show paused"
                    bordered
                    size="small"
                    checked={filters.showPaused}
                    onChange={(e) => setFilters({ showPaused: e ?? undefined })}
                />
                {extraControls}
            </div>

            <BindLogic logic={hogFunctionsListLogic} props={props}>
                <LemonTable
                    dataSource={filteredHogFunctions}
                    size="small"
                    loading={loading}
                    columns={columns}
                    emptyState={
                        hogFunctions.length === 0 && !loading ? (
                            `No ${humanizedType}s found`
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
                                {hiddenHogFunctions.length} hidden.{' '}
                                <Link
                                    onClick={() => {
                                        resetFilters()
                                        setFilters({ showPaused: true })
                                    }}
                                >
                                    Show all
                                </Link>
                            </div>
                        )
                    }
                />
                <HogFunctionOrderModal />
            </BindLogic>
            <div className="mb-8" />
        </>
    )
}
