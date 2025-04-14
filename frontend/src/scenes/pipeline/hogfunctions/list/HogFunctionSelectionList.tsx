import { LemonCheckbox, LemonInput, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { HogFunctionIcon } from '../HogFunctionIcon'
import { hogFunctionListLogic, HogFunctionListLogicProps } from './hogFunctionListLogic'

// Define props including selection state
export type HogFunctionSelectionListProps = HogFunctionListLogicProps & {
    selectedHogFunctionIds: string[]
    onSelectionChange: (selectedIds: string[]) => void
}

export function HogFunctionSelectionList({
    selectedHogFunctionIds,
    onSelectionChange,
    ...props
}: HogFunctionSelectionListProps): JSX.Element {
    const logic = hogFunctionListLogic(props)
    const { loading, filteredHogFunctions, filters, hogFunctions } = useValues(logic)
    const { loadHogFunctions, setFilters, resetFilters } = useActions(logic)

    useEffect(() => loadHogFunctions(), [])

    // Sort the functions to show selected ones first
    const sortedHogFunctions = useMemo(() => {
        return [...filteredHogFunctions].sort((a, b) => {
            const aSelected = selectedHogFunctionIds.includes(a.id)
            const bSelected = selectedHogFunctionIds.includes(b.id)

            if (aSelected && !bSelected) {
                return -1 // a comes first
            }
            if (!aSelected && bSelected) {
                return 1 // b comes first
            }
            return a.name.localeCompare(b.name)
        })
    }, [filteredHogFunctions, selectedHogFunctionIds])

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
                <span className="text-muted text-sm mr-2">{selectedHogFunctionIds.length} selected</span>
            </div>

            <BindLogic logic={hogFunctionListLogic} props={props}>
                <LemonTable
                    dataSource={sortedHogFunctions}
                    size="small"
                    loading={loading}
                    columns={[
                        // Selection column
                        {
                            width: 0,
                            render: function RenderSelection(_, hogFunction) {
                                return (
                                    <LemonCheckbox
                                        className="px-1.5"
                                        checked={selectedHogFunctionIds.includes(hogFunction.id)}
                                        onChange={() => {
                                            const newSelection = selectedHogFunctionIds.includes(hogFunction.id)
                                                ? selectedHogFunctionIds.filter((id) => id !== hogFunction.id)
                                                : [...selectedHogFunctionIds, hogFunction.id]
                                            onSelectionChange(newSelection)
                                        }}
                                    />
                                )
                            },
                        },
                        // Icon column
                        {
                            title: '',
                            width: 0,
                            render: function RenderIcon(_, hogFunction) {
                                return <HogFunctionIcon src={hogFunction.icon_url} size="small" />
                            },
                        },
                        // Name and Description column
                        {
                            title: 'Name',
                            key: 'name',
                            dataIndex: 'name',
                            sorter: true,
                            render: (_, hogFunction) => {
                                return (
                                    <Tooltip title={hogFunction.description || hogFunction.name}>
                                        {/* Clicking name shouldn't navigate away here, just shows tooltip */}
                                        <span className="font-medium">{hogFunction.name}</span>
                                    </Tooltip>
                                )
                            },
                        },
                        // Status column
                        {
                            title: 'Status',
                            key: 'enabled',
                            sorter: (a) => (a.enabled ? 1 : -1),
                            width: 100,
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
