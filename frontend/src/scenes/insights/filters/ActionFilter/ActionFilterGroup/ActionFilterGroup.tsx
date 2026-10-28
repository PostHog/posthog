import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCopy, IconEllipsis, IconPencil, IconPlusSmall, IconTrash, IconUndo } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import {
    DefinitionPopoverRenderer,
    TaxonomicFilterGroupType,
    isQuickFilterItem,
    quickFilterToPropertyFilters,
} from 'lib/components/TaxonomicFilter/types'
import {
    TaxonomicPopover,
    TaxonomicPopoverProps,
    TaxonomicStringPopover,
} from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { teamLogic } from 'scenes/teamLogic'

import { GroupNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, InsightType } from '~/types'

import { MathCategory, mathsLogic } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

import { ActionFilterRow, MathSelector } from '../ActionFilterRow/ActionFilterRow'
import { taxonomicGroupTypeToSeriesNodeKind } from '../ActionFilterRow/actionFilterRowUtils'
import { getDefaultMathHogQLExpression } from '../ActionFilterRow/mathUtils'
import { MathAvailability } from '../ActionFilterRow/types'
import { entityFilterLogic } from '../entityFilterLogic'
import { actionFilterGroupLogic } from './actionFilterGroupLogic'
import { nestedFilterLogic } from './nestedFilterLogic'

interface ActionFilterGroupProps {
    node: GroupNode
    /** Sidecar row identity, for the drag key and the group's own logic key. */
    uuid: string
    index: number
    typeKey: string
    filterCount: number
    sortable: boolean
    disabled?: boolean
    readOnly?: boolean
    hideDeleteBtn?: boolean
    hasBreakdown: boolean
    showSeriesIndicator?: boolean
    seriesIndicatorType?: 'alpha' | 'numeric'
    actionsTaxonomicGroupTypes?: any[]
    mathAvailability?: MathAvailability
    showNumericalPropsOnly?: boolean
    dataWarehousePopoverFields?: any[]
    excludedProperties?: TaxonomicPopoverProps['excludedProperties']
    includeHiddenEvents?: TaxonomicPopoverProps['includeHiddenEvents']
    groupTitle?: string
    trendsDisplayCategory?: any
    insightType?: InsightType
    definitionPopoverRenderer?: DefinitionPopoverRenderer
}

export function ActionFilterGroup({
    node,
    uuid,
    index,
    typeKey,
    filterCount,
    sortable,
    disabled = false,
    readOnly = false,
    hasBreakdown,
    showSeriesIndicator,
    seriesIndicatorType = 'alpha',
    mathAvailability = MathAvailability.All,
    actionsTaxonomicGroupTypes = [],
    showNumericalPropsOnly,
    dataWarehousePopoverFields,
    excludedProperties,
    includeHiddenEvents,
    groupTitle,
    trendsDisplayCategory,
    insightType,
    definitionPopoverRenderer,
}: ActionFilterGroupProps): JSX.Element {
    const effectiveActionsTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.SuggestedFilters,
        ...actionsTaxonomicGroupTypes,
    ].filter((groupType) => groupType !== TaxonomicFilterGroupType.DataWarehouse)

    const { currentTeamId } = useValues(teamLogic)
    const { removeSeries, splitGroup, duplicateSeries, showModal, selectSeries } = useActions(
        entityFilterLogic({ typeKey })
    )
    const { mathDefinitions } = useValues(mathsLogic)
    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({ id: uuid })

    const groupLogic = actionFilterGroupLogic({ filterUuid: uuid, typeKey, groupIndex: index })
    const { nestedNodes, nestedRows, operator, isHogQLDropdownVisible, groupNode } = useValues(groupLogic)
    const {
        addNestedSeries,
        updateNestedSeriesProperties,
        setMath,
        setMathProperty,
        setMathHogQL,
        setHogQLDropdownVisible,
    } = useActions(groupLogic)
    const defaultMathHogQLExpression = getDefaultMathHogQLExpression(insightType)

    const mathCategory = mathDefinitions[node.math || BaseMathType.TotalCount]?.category
    const hasSecondaryMathDropdown =
        mathCategory === MathCategory.PropertyValue || mathCategory === MathCategory.HogQLExpression
    const showMath = mathAvailability !== MathAvailability.None && mathAvailability !== MathAvailability.FunnelsOnly

    const mathSelectorProps = {
        size: 'small' as const,
        math: node.math,
        mathGroupTypeIndex: node.math_group_type_index,
        index,
        onMathSelect: (_: number, math: any) => setMath(math, defaultMathHogQLExpression),
        disabled: disabled || readOnly,
        mathAvailability,
        trendsDisplayCategory,
    }

    return (
        <li
            className="ActionFilterGroup relative min-w-0 max-w-full list-none"
            ref={setNodeRef}
            {...attributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div className="flex flex-col overflow-hidden min-w-0 border border-primary rounded hover:border-secondary">
                {/* Header */}
                <div
                    className={clsx(
                        'ActionFilterGroup--header flex flex-col gap-y-1.5 px-2.5 py-2 @min-[500px]/editor-panel:px-4 border-b border-primary'
                    )}
                >
                    {/* Row 1: letter + title + inline math (when small) | menu button */}
                    <div className="flex items-center gap-x-2 min-w-0">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 min-w-0 flex-1">
                            <div className="flex items-center gap-x-2 flex-1 min-w-[45%]">
                                {sortable && filterCount > 1 && (
                                    <span className="ActionFilterRowDragHandle" {...listeners}>
                                        <SortableDragIcon />
                                    </span>
                                )}
                                {showSeriesIndicator && (
                                    <div className="shrink-0">
                                        {seriesIndicatorType === 'numeric' ? (
                                            <SeriesGlyph style={{ borderColor: 'var(--color-border-primary)' }}>
                                                {index + 1}
                                            </SeriesGlyph>
                                        ) : (
                                            <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
                                        )}
                                    </div>
                                )}
                                {groupTitle && (
                                    <span className="font-medium text-secondary truncate min-w-0">{groupTitle}</span>
                                )}
                            </div>

                            {showMath && !hasSecondaryMathDropdown && <MathSelector {...mathSelectorProps} />}
                        </div>

                        {!readOnly && (
                            <div className="flex shrink-0 self-start pt-0.75">
                                <LemonMenu
                                    placement="bottom-end"
                                    items={[
                                        {
                                            items: [
                                                {
                                                    label: 'Split events',
                                                    size: 'medium',
                                                    icon: <IconUndo />,
                                                    onClick: () => {
                                                        splitGroup(index)
                                                        posthog.capture('split_events', {
                                                            insight_type: insightType,
                                                            team_id: currentTeamId,
                                                        })
                                                    },
                                                    'data-attr': `group-filter-split-${index}`,
                                                },
                                            ],
                                        },
                                        {
                                            items: [
                                                {
                                                    label: 'Rename',
                                                    size: 'medium',
                                                    icon: <IconPencil />,
                                                    onClick: () => {
                                                        selectSeries(index, groupNode ?? null, uuid)
                                                        showModal()
                                                    },
                                                    'data-attr': `group-filter-rename-${index}`,
                                                },
                                                {
                                                    label: 'Duplicate',
                                                    size: 'medium',
                                                    icon: <IconCopy />,
                                                    onClick: () => {
                                                        duplicateSeries(index)
                                                    },
                                                    'data-attr': `group-filter-duplicate-${index}`,
                                                },
                                                {
                                                    label: 'Delete',
                                                    size: 'medium',
                                                    status: 'danger',
                                                    icon: <IconTrash />,
                                                    onClick: () => removeSeries(index),
                                                    'data-attr': `group-filter-delete-${index}`,
                                                },
                                            ],
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        noPadding
                                        size="medium"
                                        icon={<IconEllipsis />}
                                        aria-label="Show more actions"
                                        data-attr={`group-filter-menu-${index}`}
                                    />
                                </LemonMenu>
                            </div>
                        )}
                    </div>

                    {/* Row 2: math + secondary dropdown — full width */}
                    {showMath && hasSecondaryMathDropdown && (
                        <div className="flex items-center gap-2 min-w-0">
                            <div className="flex-1 min-w-0 overflow-hidden">
                                <MathSelector {...mathSelectorProps} fullWidth truncateText={{ maxWidthClass: '' }} />
                            </div>
                            {mathCategory === MathCategory.PropertyValue && (
                                <div className="flex-1 min-w-0 overflow-hidden">
                                    <TaxonomicStringPopover
                                        fullWidth
                                        truncate
                                        size="small"
                                        groupType={
                                            (node.math_property_type as TaxonomicFilterGroupType) ||
                                            TaxonomicFilterGroupType.NumericalEventProperties
                                        }
                                        groupTypes={[
                                            TaxonomicFilterGroupType.DataWarehouseProperties,
                                            TaxonomicFilterGroupType.NumericalEventProperties,
                                            TaxonomicFilterGroupType.SessionProperties,
                                            TaxonomicFilterGroupType.PersonProperties,
                                            TaxonomicFilterGroupType.DataWarehousePersonProperties,
                                        ]}
                                        value={node.math_property}
                                        onChange={setMathProperty}
                                        eventNames={nestedNodes.map((v) => v.name).filter(Boolean) as string[]}
                                        data-attr="math-property-select"
                                        showNumericalPropsOnly={showNumericalPropsOnly}
                                        renderValue={(currentValue) => (
                                            <Tooltip
                                                title={
                                                    currentValue === '$session_duration' ? (
                                                        <>
                                                            Calculate{' '}
                                                            {mathDefinitions[node.math ?? '']?.name.toLowerCase()} of
                                                            the session duration. This is based on the{' '}
                                                            <code>$session_id</code> property associated with events.
                                                            The duration is derived from the time difference between the
                                                            first and last event for each distinct{' '}
                                                            <code>$session_id</code>.
                                                        </>
                                                    ) : (
                                                        <>
                                                            Calculate{' '}
                                                            {mathDefinitions[node.math ?? '']?.name.toLowerCase()} from
                                                            property <code>{currentValue}</code>. Note that only event
                                                            occurrences where <code>{currentValue}</code> is set with a
                                                            numeric value will be taken into account.
                                                        </>
                                                    )
                                                }
                                                placement="right"
                                            >
                                                <PropertyKeyInfo
                                                    value={currentValue}
                                                    disablePopover
                                                    type={TaxonomicFilterGroupType.EventProperties}
                                                />
                                            </Tooltip>
                                        )}
                                    />
                                </div>
                            )}
                            {mathCategory === MathCategory.HogQLExpression && (
                                <div className="min-w-0 flex-1">
                                    <LemonDropdown
                                        visible={isHogQLDropdownVisible}
                                        closeOnClickInside={false}
                                        onClickOutside={() => setHogQLDropdownVisible(false)}
                                        overlay={
                                            // eslint-disable-next-line react/forbid-dom-props
                                            <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                                                <HogQLEditor
                                                    value={node.math_hogql || defaultMathHogQLExpression}
                                                    onChange={(currentValue) => {
                                                        setMathHogQL(currentValue)
                                                        setHogQLDropdownVisible(false)
                                                    }}
                                                />
                                            </div>
                                        }
                                    >
                                        <LemonButton
                                            fullWidth
                                            type="secondary"
                                            size="small"
                                            truncate
                                            data-attr={`math-hogql-select-${index}`}
                                            onClick={() => setHogQLDropdownVisible(!isHogQLDropdownVisible)}
                                        >
                                            <code className="truncate">
                                                {node.math_hogql || defaultMathHogQLExpression}
                                            </code>
                                        </LemonButton>
                                    </LemonDropdown>
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* Events list */}
                <ul className="ActionFilterGroup--events-list flex flex-col px-4 py-2.5 bg-primary [&_.ActionFilterRow]:!border-0 [&_.ActionFilterRow]:!rounded-none [&_.ActionFilterRow]:!p-0">
                    {nestedRows.map(({ uuid: nestedUuid, node: nestedNode }, eventIndex) => {
                        const nestedLogicInstance = nestedFilterLogic({
                            groupFilterUuid: uuid,
                            nestedUuid,
                            nestedIndex: eventIndex,
                            typeKey,
                            groupIndex: index,
                        })

                        return (
                            <div key={nestedUuid}>
                                <ActionFilterRow
                                    logic={nestedLogicInstance as any}
                                    node={nestedNode}
                                    uuid={nestedUuid}
                                    index={eventIndex}
                                    typeKey={`group-${index}-${eventIndex}`}
                                    mathAvailability={MathAvailability.None}
                                    hideRename
                                    hideDuplicate
                                    hideDeleteBtn={nestedNodes.length <= 1 || readOnly}
                                    filterCount={nestedNodes.length}
                                    sortable={false}
                                    hasBreakdown={hasBreakdown}
                                    disabled={disabled || readOnly}
                                    readOnly={readOnly}
                                    actionsTaxonomicGroupTypes={actionsTaxonomicGroupTypes.filter(
                                        (t: TaxonomicFilterGroupType) => t !== TaxonomicFilterGroupType.DataWarehouse
                                    )}
                                    trendsDisplayCategory={trendsDisplayCategory}
                                    showNumericalPropsOnly={showNumericalPropsOnly}
                                    dataWarehousePopoverFields={dataWarehousePopoverFields}
                                    excludedProperties={excludedProperties}
                                    includeHiddenEvents={includeHiddenEvents}
                                    definitionPopoverRenderer={definitionPopoverRenderer}
                                />
                                {eventIndex < nestedNodes.length - 1 && (
                                    <div className="flex items-center gap-3 mx-0.5 my-2.5">
                                        <div className="flex-1 h-px bg-border-primary" />
                                        <span className="text-[11px] font-semibold text-tertiary uppercase tracking-wide">
                                            {operator}
                                        </span>
                                        <div className="flex-1 h-px bg-border-primary" />
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </ul>

                {/* Add event button */}
                {!readOnly && nestedNodes.length < 10 && (
                    <div className="ActionFilterGroup--footer px-4 py-2.5 bg-primary">
                        <TaxonomicPopover
                            data-attr={`add-group-event-${index}`}
                            groupType={TaxonomicFilterGroupType.Events}
                            value={null}
                            icon={<IconPlusSmall />}
                            sideIcon={null}
                            enableKeywordShortcuts
                            onChange={(value, groupType, item) => {
                                if (isQuickFilterItem(item)) {
                                    if (item.eventName) {
                                        const newIndex = nestedNodes.length
                                        addNestedSeries(item.eventName, item.eventName, NodeKind.EventsNode)
                                        updateNestedSeriesProperties(newIndex, quickFilterToPropertyFilters(item))
                                        posthog.capture('add_event_to_group', {
                                            insight_type: insightType,
                                            team_id: currentTeamId,
                                        })
                                    }
                                    return
                                }
                                const kind = taxonomicGroupTypeToSeriesNodeKind(groupType)
                                if (kind !== NodeKind.GroupNode && value) {
                                    addNestedSeries(String(value), item?.name || String(value), kind)
                                    posthog.capture('add_event_to_group', {
                                        insight_type: insightType,
                                        team_id: currentTeamId,
                                    })
                                }
                            }}
                            groupTypes={effectiveActionsTaxonomicGroupTypes}
                            placeholder="Add event"
                            placeholderClass=""
                            showNumericalPropsOnly={showNumericalPropsOnly}
                            dataWarehousePopoverFields={dataWarehousePopoverFields}
                            excludedProperties={excludedProperties}
                            includeHiddenEvents={includeHiddenEvents}
                        />
                    </div>
                )}
            </div>
        </li>
    )
}
