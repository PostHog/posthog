import './ActionFilter.scss'
import React, { useEffect } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { entityFilterLogic, toFilters, LocalFilter } from './entityFilterLogic'
import { ActionFilterRow, MathAvailability } from './ActionFilterRow/ActionFilterRow'
import { ActionFilter as ActionFilterType, FilterType, FunnelExclusion, InsightType, Optional } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { RenameModal } from 'scenes/insights/filters/ActionFilter/RenameModal'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../../../teamLogic'
import clsx from 'clsx'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconPlusMini } from 'lib/lemon-ui/icons'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { verticalSortableListCollisionDetection } from 'lib/sortable'

export interface ActionFilterProps {
    setFilters: (filters: FilterType) => void
    filters: Optional<FilterType, 'type'>
    typeKey: string
    addFilterDefaultOptions?: Record<string, any>
    mathAvailability?: MathAvailability
    /** Text copy for the action button to add more events/actions (graph series) */
    buttonCopy: string
    buttonType?: LemonButtonProps['type']
    /** Whether the full control is enabled or not */
    disabled?: boolean
    /** Bordered view */
    bordered?: boolean
    /** Whether actions/events can be sorted (used mainly for funnel step reordering) */
    sortable?: boolean
    /** Whether to show an indicator identifying each graph */
    showSeriesIndicator?: boolean
    /** Series badge shows A, B, C | 1, 2, 3 */
    seriesIndicatorType?: 'alpha' | 'numeric'
    /** Hide local filtering (currently used for retention insight) */
    hideFilter?: boolean
    /** Hides the rename option */
    hideRename?: boolean
    /** Hides the duplicate option */
    hideDuplicate?: boolean
    /** Whether to show the nested PropertyFilters in popover mode or not */
    propertyFiltersPopover?: boolean
    /** A limit of entities (series or funnel steps) beyond which more can't be added */
    entitiesLimit?: number
    /** Custom suffix element to show in each ActionFilterRow */
    customRowSuffix?:
        | string
        | JSX.Element
        | ((props: { filter: ActionFilterType | FunnelExclusion; index: number; onClose: () => void }) => JSX.Element)
    /** Show nested arrows to the left of property filter buttons */
    showNestedArrow?: boolean
    /** Which tabs to show for actions selector */
    actionsTaxonomicGroupTypes?: TaxonomicFilterGroupType[]
    /** Which tabs to show for property filters */
    propertiesTaxonomicGroupTypes?: TaxonomicFilterGroupType[]
    hideDeleteBtn?: boolean
    readOnly?: boolean
    renderRow?: ({
        seriesIndicator,
        prefix,
        filter,
        suffix,
        propertyFiltersButton,
        deleteButton,
        orLabel,
    }: Record<string, JSX.Element | string | undefined>) => JSX.Element
}

export const ActionFilter = React.forwardRef<HTMLDivElement, ActionFilterProps>(function ActionFilter(
    {
        setFilters,
        filters,
        typeKey,
        addFilterDefaultOptions = {},
        mathAvailability = MathAvailability.All,
        buttonCopy = '',
        disabled = false,
        sortable = false,
        showSeriesIndicator = false,
        seriesIndicatorType = 'alpha',
        hideFilter = false,
        hideRename = false,
        hideDuplicate = false,
        propertyFiltersPopover,
        customRowSuffix,
        entitiesLimit,
        showNestedArrow = false,
        actionsTaxonomicGroupTypes,
        propertiesTaxonomicGroupTypes,
        hideDeleteBtn,
        renderRow,
        buttonType = 'tertiary',
        readOnly = false,
        bordered = false,
    },
    ref
): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = entityFilterLogic({
        teamId: currentTeamId,
        setFilters,
        filters,
        typeKey,
        addFilterDefaultOptions,
    })
    const { reportFunnelStepReordered } = useActions(eventUsageLogic)

    const { localFilters } = useValues(logic)
    const { addFilter, setLocalFilters, showModal } = useActions(logic)

    // No way around this. Somehow the ordering of the logic calling each other causes stale "localFilters"
    // to be shown on the /funnels page, even if we try to use a selector with props to hydrate it
    useEffect(() => {
        setLocalFilters(filters)
    }, [filters])

    function onSortEnd({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void {
        function move(arr: LocalFilter[], from: number, to: number): LocalFilter[] {
            const clone = [...arr]
            Array.prototype.splice.call(clone, to, 0, Array.prototype.splice.call(clone, from, 1)[0])
            return clone.map((child, order) => ({ ...child, order }))
        }
        setFilters(toFilters(move(localFilters, oldIndex, newIndex)))
        if (oldIndex !== newIndex) {
            reportFunnelStepReordered()
        }
    }

    const singleFilter = entitiesLimit === 1

    const commonProps = {
        logic,
        showSeriesIndicator,
        seriesIndicatorType,
        mathAvailability,
        customRowSuffix,
        hasBreakdown: !!filters.breakdown,
        actionsTaxonomicGroupTypes,
        propertiesTaxonomicGroupTypes,
        propertyFiltersPopover,
        hideDeleteBtn,
        disabled,
        readOnly,
        renderRow,
        hideRename,
        hideDuplicate,
        onRenameClick: showModal,
        sortable,
    }

    const reachedLimit: boolean = Boolean(entitiesLimit && localFilters.length >= entitiesLimit)
    const sortedItemIds = localFilters.map((i) => i.uuid)

    return (
        <div
            className={clsx('ActionFilter', {
                'ActionFilter--bordered': bordered,
            })}
            ref={ref}
        >
            {!hideRename && !readOnly && (
                <BindLogic logic={entityFilterLogic} props={{ setFilters, filters, typeKey, addFilterDefaultOptions }}>
                    <RenameModal view={filters.insight} typeKey={typeKey} />
                </BindLogic>
            )}
            {localFilters ? (
                <ul>
                    <DndContext
                        onDragEnd={({ active, over }) => {
                            if (over && active.id !== over.id) {
                                onSortEnd({
                                    oldIndex: sortedItemIds.indexOf(active.id.toString()),
                                    newIndex: sortedItemIds.indexOf(over.id.toString()),
                                })
                            }
                        }}
                        modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                        collisionDetection={verticalSortableListCollisionDetection}
                    >
                        <SortableContext
                            disabled={!sortable}
                            items={sortedItemIds}
                            strategy={verticalListSortingStrategy}
                        >
                            {localFilters.map((filter, index) => (
                                <ActionFilterRow
                                    key={filter.uuid}
                                    typeKey={typeKey}
                                    filter={filter}
                                    index={index}
                                    filterCount={localFilters.length}
                                    showNestedArrow={showNestedArrow}
                                    singleFilter={singleFilter}
                                    hideFilter={hideFilter || readOnly}
                                    {...commonProps}
                                />
                            ))}
                        </SortableContext>
                    </DndContext>
                </ul>
            ) : null}
            {!singleFilter && (
                <div className="ActionFilter-footer">
                    {!singleFilter && (
                        <LemonButton
                            type={buttonType}
                            onClick={() => addFilter()}
                            data-attr="add-action-event-button"
                            icon={<IconPlusMini />}
                            disabled={reachedLimit || disabled || readOnly}
                            fullWidth
                        >
                            {!reachedLimit
                                ? buttonCopy || 'Action or event'
                                : `Reached limit of ${entitiesLimit} ${
                                      filters.insight === InsightType.FUNNELS ? 'steps' : 'series'
                                  }`}
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
})
