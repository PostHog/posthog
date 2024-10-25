import { LemonInput, LemonTable, LemonTableColumn, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { functionsTableLogic } from 'scenes/messaging/functionsTableLogic'
import { hogFunctionUrl } from 'scenes/pipeline/hogfunctions/urls'

import { HogFunctionType, HogFunctionTypeType } from '~/types'

import { HogFunctionIcon } from '../pipeline/hogfunctions/HogFunctionIcon'
import { HogFunctionStatusIndicator } from '../pipeline/hogfunctions/HogFunctionStatusIndicator'

export interface FunctionsTableProps {
    type?: HogFunctionTypeType
}

export function FunctionsTableFilters(): JSX.Element | null {
    const { filters } = useValues(functionsTableLogic)
    const { setFilters } = useActions(functionsTableLogic)

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    value={filters.search ?? ''}
                    onChange={(e) => setFilters({ search: e })}
                />
            </div>
        </div>
    )
}

export function FunctionsTable({ type }: FunctionsTableProps): JSX.Element {
    const { hogFunctions, filteredHogFunctions, loading } = useValues(functionsTableLogic({ type }))
    const { deleteHogFunction, resetFilters } = useActions(functionsTableLogic({ type }))

    return (
        <BindLogic logic={functionsTableLogic} props={{ type }}>
            <div className="space-y-2">
                <FunctionsTableFilters />

                <LemonTable
                    dataSource={filteredHogFunctions}
                    size="small"
                    loading={loading}
                    columns={[
                        {
                            title: 'App',
                            width: 0,
                            render: function RenderAppInfo(_, hogFucntion) {
                                return <HogFunctionIcon src={hogFucntion.icon_url} size="small" />
                            },
                        },
                        {
                            title: 'Name',
                            sticky: true,
                            sorter: true,
                            key: 'name',
                            dataIndex: 'name',
                            render: function RenderPluginName(_, hogFunction) {
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

                        updatedAtColumn() as LemonTableColumn<HogFunctionType, any>,
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
                                                items={[
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
                            'Nothing found'
                        ) : (
                            <>
                                Nothing matches filters. <Link onClick={() => resetFilters()}>Clear filters</Link>{' '}
                            </>
                        )
                    }
                />
            </div>
        </BindLogic>
    )
}
