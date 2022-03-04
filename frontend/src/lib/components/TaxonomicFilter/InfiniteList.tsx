import './InfiniteList.scss'
import '../Popup/Popup.scss'
import React, { useState } from 'react'
import { Empty, Skeleton, Tag } from 'antd'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import {
    getKeyMapping,
    PropertyKeyDescription,
    PropertyKeyInfo,
    PropertyKeyTitle,
} from 'lib/components/PropertyKeyInfo'
import { BindLogic, Provider, useActions, useValues } from 'kea'
import { infiniteListLogic, NO_ITEM_SELECTED } from './infiniteListLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import ReactDOM from 'react-dom'
import { usePopper } from 'react-popper'
import { ActionType, CohortType, EventDefinition, KeyMapping, PropertyDefinition } from '~/types'
import { AimOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { ActionSelectInfo } from 'scenes/insights/ActionSelectInfo'
import { urls } from 'scenes/urls'
import { dayjs } from 'lib/dayjs'
import { FEATURE_FLAGS, STALE_EVENT_SECONDS } from 'lib/constants'
import { Tooltip } from '../Tooltip'
import clsx from 'clsx'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { definitionPopupLogic } from 'lib/components/DefinitionPopup/definitionPopupLogic'
import { ControlledDefinitionPopupContents } from 'lib/components/DefinitionPopup/DefinitionPopupContents'
import { pluralize } from 'lib/utils'

enum ListTooltip {
    None = 0,
    Left = 1,
    Right = 2,
}

export function tooltipDesiredState(element?: Element | null): ListTooltip {
    let desiredState: ListTooltip = ListTooltip.None
    const rect = element?.getBoundingClientRect()
    if (rect) {
        if (window.innerWidth - rect.right > 300) {
            desiredState = ListTooltip.Right
        } else if (rect.left > 300) {
            desiredState = ListTooltip.Left
        }
    }
    return desiredState
}

const staleIndicator = (parsedLastSeen: dayjs.Dayjs | null): JSX.Element => {
    return (
        <Tooltip
            title={
                <>
                    This event was last seen <b>{parsedLastSeen ? parsedLastSeen.fromNow() : 'a while ago'}</b>.
                </>
            }
        >
            <Tag className="lemonade-tag">Stale</Tag>
        </Tooltip>
    )
}

const unusedIndicator = (eventNames: string[]): JSX.Element => {
    return (
        <Tooltip
            title={
                <>
                    This property has not been seen on{' '}
                    {eventNames ? (
                        <>
                            the event{eventNames.length > 1 ? 's' : ''}{' '}
                            {eventNames.map((e, index) => (
                                <>
                                    {index === 0 ? '' : index === eventNames.length - 1 ? ' and ' : ', '}
                                    <strong>"{e}"</strong>
                                </>
                            ))}
                        </>
                    ) : (
                        'this event'
                    )}
                    , but has been seen on other events.
                </>
            }
        >
            <Tag className="lemonade-tag">Not seen</Tag>
        </Tooltip>
    )
}

const renderItemContents = ({
    item,
    listGroupType,
    featureFlags,
    eventNames,
}: {
    item: TaxonomicDefinitionTypes
    listGroupType: TaxonomicFilterGroupType
    featureFlags: FeatureFlagsSet
    eventNames: string[]
}): JSX.Element | string => {
    const parsedLastSeen = (item as EventDefinition).last_seen_at ? dayjs((item as EventDefinition).last_seen_at) : null
    const isStale =
        (featureFlags[FEATURE_FLAGS.STALE_EVENTS] &&
            listGroupType === TaxonomicFilterGroupType.Events &&
            !parsedLastSeen) ||
        dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS

    const isUnusedEventProperty =
        featureFlags[FEATURE_FLAGS.UNSEEN_EVENT_PROPERTIES] &&
        (listGroupType === TaxonomicFilterGroupType.NumericalEventProperties ||
            listGroupType === TaxonomicFilterGroupType.EventProperties) &&
        (item as PropertyDefinition).is_event_property !== null &&
        !(item as PropertyDefinition).is_event_property

    return listGroupType === TaxonomicFilterGroupType.EventProperties ||
        listGroupType === TaxonomicFilterGroupType.NumericalEventProperties ||
        listGroupType === TaxonomicFilterGroupType.PersonProperties ||
        listGroupType === TaxonomicFilterGroupType.Events ||
        listGroupType === TaxonomicFilterGroupType.CustomEvents ||
        listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix) ? (
        <>
            <div className={clsx(isStale && 'text-muted')}>
                <PropertyKeyInfo value={item.name ?? ''} disablePopover style={{ maxWidth: '100%' }} />
            </div>
            {isStale && staleIndicator(parsedLastSeen)}
            {isUnusedEventProperty && unusedIndicator(eventNames)}
        </>
    ) : listGroupType === TaxonomicFilterGroupType.Elements ? (
        <PropertyKeyInfo type="element" value={item.name ?? ''} disablePopover style={{ maxWidth: '100%' }} />
    ) : (
        item.name ?? ''
    )
}

const renderItemPopupWithoutTaxonomy = (
    item: PropertyDefinition | CohortType | ActionType,
    listGroupType: TaxonomicFilterGroupType,
    group: TaxonomicFilterGroup
): JSX.Element | string => {
    const width = 265
    let data: KeyMapping | null = null
    const value = group.getValue(item)

    if (value) {
        if (listGroupType === TaxonomicFilterGroupType.Actions && 'id' in item) {
            return (
                <div style={{ width, overflowWrap: 'break-word' }}>
                    <AimOutlined /> Actions
                    <Link to={urls.action(item.id)} style={{ float: 'right' }} tabIndex={-1}>
                        edit
                    </Link>
                    <br />
                    <h3>
                        <PropertyKeyInfo value={item.name ?? ''} style={{ maxWidth: '100%' }} />
                    </h3>
                    {item && <ActionSelectInfo entity={item as ActionType} />}
                </div>
            )
        }

        if (
            // NB: also update "selectedItemHasPopup" below
            listGroupType === TaxonomicFilterGroupType.Events ||
            listGroupType === TaxonomicFilterGroupType.EventProperties ||
            listGroupType === TaxonomicFilterGroupType.NumericalEventProperties ||
            listGroupType === TaxonomicFilterGroupType.PersonProperties
        ) {
            data = getKeyMapping(value.toString(), 'event')
        } else if (listGroupType === TaxonomicFilterGroupType.Elements) {
            data = getKeyMapping(value.toString(), 'element')
        }

        if (data) {
            return (
                <div style={{ width, overflowWrap: 'break-word' }}>
                    <PropertyKeyTitle data={data} />
                    {data.description ? <hr /> : null}
                    <PropertyKeyDescription
                        data={data}
                        value={value.toString()}
                        propertyType={(item as PropertyDefinition)?.property_type}
                    />
                    {'volume_30_day' in item && (item.volume_30_day || 0) > 0 ? (
                        <p>
                            Seen <strong>{item.volume_30_day}</strong> times.{' '}
                        </p>
                    ) : null}
                    {'query_usage_30_day' in item && (item.query_usage_30_day || 0) > 0 ? (
                        <p>
                            Used in <strong>{item.query_usage_30_day}</strong> queries.
                        </p>
                    ) : null}
                </div>
            )
        }
    }

    return item.name ?? ''
}

const selectedItemHasPopup = (
    item?: TaxonomicDefinitionTypes,
    listGroupType?: TaxonomicFilterGroupType,
    group?: TaxonomicFilterGroup,
    showNewPopups: boolean = false
): boolean => {
    if (showNewPopups) {
        return (
            // NB: also update "renderItemPopup" above
            !!item &&
            !!group?.getValue(item) &&
            !!listGroupType &&
            ([
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.Elements,
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.CustomEvents,
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.NumericalEventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.CohortsWithAllUsers,
            ].includes(listGroupType) ||
                listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix))
        )
    }

    return (
        // NB: also update "renderItemPopup" above
        !!item &&
        !!group?.getValue(item) &&
        (listGroupType === TaxonomicFilterGroupType.Actions ||
            ((listGroupType === TaxonomicFilterGroupType.Elements ||
                listGroupType === TaxonomicFilterGroupType.Events ||
                listGroupType === TaxonomicFilterGroupType.EventProperties ||
                listGroupType === TaxonomicFilterGroupType.NumericalEventProperties ||
                listGroupType === TaxonomicFilterGroupType.PersonProperties) &&
                !!getKeyMapping(
                    group?.getValue(item),
                    listGroupType === TaxonomicFilterGroupType.Elements ? 'element' : 'event'
                )))
    )
}

export function InfiniteList(): JSX.Element {
    const { mouseInteractionsEnabled, activeTab, searchQuery, value, groupType, eventNames } =
        useValues(taxonomicFilterLogic)
    const { selectItem } = useActions(taxonomicFilterLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const {
        isLoading,
        results,
        index,
        listGroupType,
        group,
        selectedItem,
        selectedItemInView,
        isExpandable,
        totalResultCount,
        totalListCount,
        expandedCount,
        showPopover,
    } = useValues(infiniteListLogic)
    const { onRowsRendered, setIndex, expand, updateRemoteItem } = useActions(infiniteListLogic)

    const isActiveTab = listGroupType === activeTab
    const showEmptyState = totalListCount === 0 && !isLoading
    const showNewPopups = !!featureFlags[FEATURE_FLAGS.COLLABORATIONS_TAXONOMY]

    const [referenceElement, setReferenceElement] = useState<HTMLDivElement | null>(null)
    const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null)

    const { styles, attributes, forceUpdate } = usePopper(referenceElement, popperElement, {
        placement: 'right',
        modifiers: [
            {
                name: 'offset',
                options: {
                    offset: [0, 10],
                },
            },
            {
                name: 'preventOverflow',
                options: {
                    padding: 10,
                },
            },
        ],
    })

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const item = results[rowIndex]
        const itemValue = item ? group?.getValue?.(item) : null
        const isSelected = listGroupType === groupType && itemValue === value
        const isHighlighted = rowIndex === index && isActiveTab

        const commonDivProps: React.HTMLProps<HTMLDivElement> = {
            key: `item_${rowIndex}`,
            className: clsx(
                'taxonomic-list-row',
                rowIndex === index && mouseInteractionsEnabled && 'hover',
                isSelected && 'selected'
            ),
            onMouseOver: () => (mouseInteractionsEnabled ? setIndex(rowIndex) : setIndex(NO_ITEM_SELECTED)),
            // if the popper is not enabled then don't leave the row selected when the mouse leaves it
            onMouseLeave: () => (mouseInteractionsEnabled && !showPopover ? setIndex(NO_ITEM_SELECTED) : null),
            style: style,
            ref: isHighlighted ? setReferenceElement : null,
        }

        return item && group ? (
            <div
                {...commonDivProps}
                data-attr={`prop-filter-${listGroupType}-${rowIndex}`}
                onClick={() => selectItem(group, itemValue ?? null, item)}
            >
                {renderItemContents({
                    item,
                    listGroupType,
                    featureFlags,
                    eventNames,
                })}
            </div>
        ) : !item && rowIndex === totalListCount - 1 && isExpandable && !isLoading ? (
            <div
                {...commonDivProps}
                className={`${commonDivProps.className} expand-row`}
                data-attr={`expand-list-${listGroupType}`}
                onClick={expand}
            >
                {group.expandLabel?.({ count: totalResultCount, expandedCount }) ??
                    `Click here to see ${expandedCount - totalResultCount} more ${pluralize(
                        expandedCount - totalResultCount,
                        'row',
                        'rows',
                        false
                    )}`}
            </div>
        ) : (
            <div
                {...commonDivProps}
                className={`${commonDivProps.className} skeleton-row`}
                data-attr={`prop-skeleton-${listGroupType}-${rowIndex}`}
            >
                <Skeleton active title={false} paragraph={{ rows: 1 }} />
            </div>
        )
    }

    return (
        <div
            className={clsx('taxonomic-infinite-list', showEmptyState && 'empty-infinite-list')}
            style={{ flexGrow: 1 }}
        >
            {showEmptyState ? (
                <div className="no-infinite-results">
                    <Empty
                        description={
                            <>
                                {searchQuery ? (
                                    <>
                                        No results for "<strong>{searchQuery}</strong>"
                                    </>
                                ) : (
                                    'No results'
                                )}
                            </>
                        }
                    />
                </div>
            ) : (
                <AutoSizer>
                    {({ height, width }) => (
                        <List
                            width={width}
                            height={height}
                            rowCount={isLoading && totalListCount === 0 ? 7 : totalListCount}
                            overscanRowCount={100}
                            rowHeight={32}
                            rowRenderer={renderItem}
                            onRowsRendered={onRowsRendered}
                            scrollToIndex={index}
                        />
                    )}
                </AutoSizer>
            )}
            {isActiveTab &&
            selectedItemInView &&
            selectedItemHasPopup(selectedItem, listGroupType, group, showNewPopups) &&
            tooltipDesiredState(referenceElement) !== ListTooltip.None &&
            showPopover ? (
                <Provider>
                    {ReactDOM.createPortal(
                        selectedItem && group ? (
                            showNewPopups ? (
                                <BindLogic
                                    logic={definitionPopupLogic}
                                    props={{
                                        type: listGroupType,
                                        updateRemoteItem,
                                    }}
                                >
                                    <ControlledDefinitionPopupContents
                                        item={selectedItem}
                                        group={group}
                                        popper={{
                                            styles: styles.popper,
                                            attributes: attributes.popper,
                                            forceUpdate,
                                            setRef: setPopperElement,
                                            ref: popperElement,
                                        }}
                                    />
                                </BindLogic>
                            ) : (
                                <div
                                    className="popper-tooltip click-outside-block Popup Popup__box"
                                    ref={setPopperElement}
                                    // zIndex: 1063 ensures it opens above the overlay and taxonomic filter
                                    style={{ ...styles.popper, transition: 'none', zIndex: 1063 }}
                                    {...attributes.popper}
                                >
                                    {renderItemPopupWithoutTaxonomy(
                                        selectedItem as PropertyDefinition | CohortType | ActionType,
                                        listGroupType,
                                        group
                                    )}
                                </div>
                            )
                        ) : null,
                        document.querySelector('body') as HTMLElement
                    )}
                </Provider>
            ) : null}
        </div>
    )
}
