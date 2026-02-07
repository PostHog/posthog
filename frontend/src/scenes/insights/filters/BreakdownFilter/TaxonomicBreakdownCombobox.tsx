import { Combobox } from '@base-ui/react/combobox'
import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef, useState } from 'react'

import { IconCheck, IconEllipsis, IconSearch, IconX } from '@posthog/icons'
import { LemonButtonWithDropdown } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { isInsightVizNode, isRetentionQuery } from '~/queries/utils'
import { ChartDisplayType, GroupTypeIndex, InsightLogicProps } from '~/types'

import { BreakdownTagMenu } from './BreakdownTagMenu'
import { breakdownTagLogic } from './breakdownTagLogic'
import {
    BreakdownComboboxItem,
    TaxonomicBreakdownComboboxLogicProps,
    taxonomicBreakdownComboboxLogic,
} from './taxonomicBreakdownComboboxLogic'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { isAllCohort, isCohort } from './taxonomicBreakdownFilterUtils'

interface TaxonomicBreakdownComboboxProps {
    insightProps: InsightLogicProps
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    disabledReason?: string
    updateBreakdownFilter: (breakdownFilter: BreakdownFilter) => void
    updateDisplay: (display: ChartDisplayType | undefined) => void
    disablePropertyInfo?: boolean
    size?: 'small' | 'medium'
}

export function TaxonomicBreakdownCombobox({
    insightProps,
    isTrends,
    disabledReason,
    disablePropertyInfo,
    size = 'medium',
}: TaxonomicBreakdownComboboxProps): JSX.Element {
    const { allEventNames, query } = useValues(insightVizDataLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { breakdownArray, isAddBreakdownDisabled, includeSessions, currentDataWarehouseSchemaColumns } =
        useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown, removeBreakdown } = useActions(taxonomicBreakdownFilterLogic)

    const inputRef = useRef<HTMLInputElement>(null!)

    let taxonomicGroupTypes: TaxonomicFilterGroupType[]
    if (isRetentionQuery(query) || (isInsightVizNode(query) && isRetentionQuery(query.source))) {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.CohortsWithAllUsers,
        ]
    } else {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.EventFeatureFlags,
            TaxonomicFilterGroupType.EventMetadata,
            ...groupsTaxonomicTypes,
            TaxonomicFilterGroupType.CohortsWithAllUsers,
            ...(includeSessions ? [TaxonomicFilterGroupType.SessionProperties] : []),
            TaxonomicFilterGroupType.HogQLExpression,
            TaxonomicFilterGroupType.DataWarehouseProperties,
            TaxonomicFilterGroupType.DataWarehousePersonProperties,
        ]
    }

    const taxonomicFilterLogicKey = `taxonomicBreakdownCombobox-${insightProps.dashboardItemId || 'new'}`

    const comboboxLogicProps: TaxonomicBreakdownComboboxLogicProps = {
        insightProps,
        taxonomicGroupTypes,
        eventNames: allEventNames,
        schemaColumns: currentDataWarehouseSchemaColumns,
        taxonomicFilterLogicKey,
    }

    return (
        <BindLogic logic={taxonomicBreakdownComboboxLogic} props={comboboxLogicProps}>
            <TaxonomicBreakdownComboboxInner
                insightProps={insightProps}
                isTrends={isTrends}
                disabledReason={disabledReason}
                disablePropertyInfo={disablePropertyInfo}
                size={size}
                inputRef={inputRef}
                breakdownArray={breakdownArray}
                isAddBreakdownDisabled={isAddBreakdownDisabled}
                addBreakdown={addBreakdown}
                removeBreakdown={removeBreakdown}
            />
        </BindLogic>
    )
}

interface TaxonomicBreakdownComboboxInnerProps {
    insightProps: InsightLogicProps
    isTrends: boolean
    disabledReason?: string
    disablePropertyInfo?: boolean
    size: 'small' | 'medium'
    inputRef: React.RefObject<HTMLInputElement>
    breakdownArray: any[]
    isAddBreakdownDisabled: boolean
    addBreakdown: (value: any, group: any) => void
    removeBreakdown: (value: string | number, type: string) => void
}

function TaxonomicBreakdownComboboxInner({
    insightProps,
    isTrends,
    disabledReason,
    disablePropertyInfo,
    size,
    inputRef,
    breakdownArray,
    isAddBreakdownDisabled,
    addBreakdown,
    removeBreakdown,
}: TaxonomicBreakdownComboboxInnerProps): JSX.Element {
    const { allGroupedItems, allItems, searchQuery, hasHogQLGroup, remoteResultsLoading } = useValues(
        taxonomicBreakdownComboboxLogic
    )
    const { setSearchQuery } = useActions(taxonomicBreakdownComboboxLogic)
    const [open, setOpen] = useState(false)

    const handleSelect = useCallback(
        (item: BreakdownComboboxItem) => {
            addBreakdown(item.value, item.taxonomicGroup)
            if (!isTrends) {
                setOpen(false)
            }
            setSearchQuery('')
            inputRef.current?.focus()
        },
        [addBreakdown, isTrends, setSearchQuery, inputRef]
    )

    const handleHogQLSubmit = useCallback(
        (value: string | number | null) => {
            if (!value) {
                return
            }
            const taxonomicGroup = {
                type: TaxonomicFilterGroupType.HogQLExpression,
                name: 'SQL expression',
                searchPlaceholder: null,
                getPopoverHeader: () => 'SQL expression',
            }

            addBreakdown(value, taxonomicGroup)
            if (!isTrends) {
                setOpen(false)
            }
        },
        [addBreakdown, isTrends]
    )

    const getItemString = useCallback((item: BreakdownComboboxItem | null): string => {
        if (!item) {
            return ''
        }
        return item.name
    }, [])

    const selectedBreakdownIds = useMemo(() => {
        const ids = new Set<string>()
        for (const breakdown of breakdownArray) {
            if (typeof breakdown === 'object' && breakdown.property != null) {
                ids.add(`${breakdown.type || 'event'}::${breakdown.property}`)
            } else if (breakdown != null) {
                ids.add(String(breakdown))
            }
        }
        return ids
    }, [breakdownArray])

    return (
        <Combobox.Root
            items={allItems}
            filter={null}
            itemToStringValue={getItemString}
            open={open}
            onOpenChange={setOpen}
            autoHighlight
        >
            <div className="flex flex-col gap-2">
                {/* Input area with chips */}
                <div
                    className="group input-like flex gap-1 items-center flex-wrap relative w-full bg-fill-input border border-primary focus-within:ring-primary py-1 px-2 cursor-text"
                    onClick={() => {
                        if (!disabledReason) {
                            setOpen(true)
                            inputRef.current?.focus()
                        }
                    }}
                >
                    <IconSearch className="size-4 text-tertiary shrink-0" />

                    {breakdownArray.map((breakdown) => (
                        <BreakdownChip
                            key={typeof breakdown === 'object' ? breakdown.property : breakdown}
                            breakdown={breakdown}
                            isTrends={isTrends}
                            insightProps={insightProps}
                            disablePropertyInfo={disablePropertyInfo}
                            onRemove={removeBreakdown}
                            size={size}
                        />
                    ))}

                    {!isAddBreakdownDisabled && (
                        <Combobox.Input
                            ref={inputRef}
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            aria-label="Search breakdown properties"
                            placeholder={breakdownArray.length === 0 ? 'Add breakdown...' : ''}
                            className="flex-1 min-w-[80px] px-1 py-0.5 text-sm focus:outline-none border-transparent bg-transparent"
                            disabled={!!disabledReason}
                        />
                    )}
                </div>

                {/* Dropdown popup */}
                <Combobox.Portal>
                    <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4}>
                        <Combobox.Popup className="primitive-menu-content min-w-[300px] max-w-[400px] flex flex-col max-h-[min(400px,var(--available-height))]">
                            <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                                <Combobox.List className="flex flex-col gap-px p-1">
                                    {allGroupedItems.map((group) => (
                                        <Combobox.Group
                                            key={group.type}
                                            items={group.items}
                                            className="flex flex-col gap-px"
                                        >
                                            <Combobox.GroupLabel className="px-2 py-1 sticky top-0 bg-surface-primary z-1">
                                                <Label intent="menu">{group.name}</Label>
                                            </Combobox.GroupLabel>
                                            <Combobox.Collection>
                                                {(item: BreakdownComboboxItem) => {
                                                    const isSelected =
                                                        selectedBreakdownIds.has(item.id) ||
                                                        selectedBreakdownIds.has(String(item.value))
                                                    return (
                                                        <Combobox.Item
                                                            key={item.id}
                                                            value={item}
                                                            onClick={() => handleSelect(item)}
                                                            render={(props) => (
                                                                <ButtonPrimitive
                                                                    {...props}
                                                                    menuItem
                                                                    fullWidth
                                                                    active={isSelected}
                                                                >
                                                                    {item.icon && (
                                                                        <span className="shrink-0">{item.icon}</span>
                                                                    )}
                                                                    <span className="truncate flex-1">
                                                                        <PropertyKeyInfo
                                                                            value={item.name}
                                                                            disablePopover
                                                                            type={item.groupType}
                                                                        />
                                                                    </span>
                                                                    {isSelected && (
                                                                        <IconCheck className="size-4 text-success shrink-0" />
                                                                    )}
                                                                </ButtonPrimitive>
                                                            )}
                                                        />
                                                    )
                                                }}
                                            </Combobox.Collection>
                                        </Combobox.Group>
                                    ))}

                                    {allGroupedItems.length === 0 && !remoteResultsLoading && (
                                        <div className="px-3 py-4 text-center text-sm text-muted">
                                            {searchQuery ? 'No results found' : 'No properties available'}
                                        </div>
                                    )}

                                    {remoteResultsLoading && allGroupedItems.length === 0 && (
                                        <div className="px-3 py-4 text-center text-sm text-muted">Loading...</div>
                                    )}
                                </Combobox.List>

                                {/* HogQL Expression section */}
                                {hasHogQLGroup && (
                                    <div className="border-t border-primary">
                                        <div className="px-2 py-1">
                                            <Label intent="menu">SQL expression</Label>
                                        </div>
                                        <div className="px-2 pb-2">
                                            <HogQLEditor
                                                onChange={handleHogQLSubmit}
                                                value=""
                                                submitText="Add SQL expression"
                                                disableAutoFocus
                                            />
                                        </div>
                                    </div>
                                )}
                            </ScrollableShadows>
                        </Combobox.Popup>
                    </Combobox.Positioner>
                </Combobox.Portal>
            </div>
        </Combobox.Root>
    )
}

interface BreakdownChipProps {
    breakdown: any
    isTrends: boolean
    insightProps: InsightLogicProps
    disablePropertyInfo?: boolean
    onRemove: (value: string | number, type: string) => void
    size: 'small' | 'medium'
}

function BreakdownChip({
    breakdown,
    isTrends,
    insightProps,
    disablePropertyInfo,
    onRemove,
}: BreakdownChipProps): JSX.Element {
    const isMultiBreakdown = typeof breakdown === 'object'
    const breakdownValue = isMultiBreakdown ? breakdown.property : breakdown
    const breakdownType = isMultiBreakdown ? breakdown.type || 'event' : 'event'

    const { cohortsById } = useValues(cohortsModel)
    const { groupTypes } = useValues(groupsModel)

    const logicProps = { insightProps, breakdown: breakdownValue, breakdownType, isTrends }
    const { isHistogramable, isNormalizeable } = useValues(breakdownTagLogic(logicProps))

    const showMenu = isHistogramable || isNormalizeable

    let displayName: string | number = breakdownValue

    if (isAllCohort(breakdownValue)) {
        displayName = 'All Users'
    } else if (isCohort(breakdownValue)) {
        displayName = cohortsById[breakdownValue]?.name || `Cohort ${breakdownValue}`
    } else if (breakdownType === 'event_metadata' && String(breakdownValue).startsWith('$group_')) {
        const group = groupTypes.get(
            parseInt(String(breakdownValue).replace('$group_', '')) as unknown as GroupTypeIndex
        )
        if (group) {
            displayName = group.name_singular || group.group_type
        }
    } else {
        displayName = extractDisplayLabel(String(breakdownValue))
    }

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <span className="inline-flex items-center gap-0.5 bg-fill-button-tertiary rounded-sm px-1.5 py-0.5 text-xs font-medium max-w-[200px]">
                <span className="truncate">
                    {breakdownType === 'hogql' ? (
                        <HoqQLPropertyInfo value={String(displayName)} />
                    ) : (
                        <PropertyKeyInfo
                            value={String(displayName)}
                            disablePopover={disablePropertyInfo}
                            type={
                                breakdownType
                                    ? PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[breakdownType]
                                    : TaxonomicFilterGroupType.EventProperties
                            }
                        />
                    )}
                </span>

                {showMenu && (
                    <LemonButtonWithDropdown
                        size="xsmall"
                        icon={<IconEllipsis />}
                        onClick={(e) => e.stopPropagation()}
                        dropdown={{
                            overlay: <BreakdownTagMenu />,
                            closeOnClickInside: false,
                        }}
                        className="p-0.5"
                    />
                )}

                <ButtonPrimitive
                    iconOnly
                    size="xs"
                    onClick={(e) => {
                        e.stopPropagation()
                        onRemove(breakdownValue, breakdownType)
                    }}
                    aria-label="Remove breakdown"
                    className="p-0"
                >
                    <IconX className="size-3 text-tertiary" />
                </ButtonPrimitive>
            </span>
        </BindLogic>
    )
}
