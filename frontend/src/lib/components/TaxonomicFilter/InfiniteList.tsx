import './InfiniteList.scss'
import '../Popup/Popup.scss'
import React, { useState } from 'react'
import { Empty, Skeleton } from 'antd'
import { AutoSizer } from 'react-virtualized/dist/commonjs/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/commonjs/List'
import {
    getKeyMapping,
    PropertyKeyDescription,
    PropertyKeyInfo,
    PropertyKeyTitle,
} from 'lib/components/PropertyKeyInfo'
import { useActions, useValues } from 'kea'
import { infiniteListLogic } from './infiniteListLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import ReactDOM from 'react-dom'
import { usePopper } from 'react-popper'
import { ActionType, CohortType, KeyMapping, PropertyDefinition } from '~/types'
import { AimOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { ActionSelectInfo } from 'scenes/insights/ActionSelectInfo'
import { urls } from 'scenes/urls'

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

const renderItemContents = ({
    item,
    listGroupType,
}: {
    item: PropertyDefinition | CohortType
    listGroupType: TaxonomicFilterGroupType
}): JSX.Element | string => {
    return listGroupType === TaxonomicFilterGroupType.EventProperties ||
        listGroupType === TaxonomicFilterGroupType.PersonProperties ||
        listGroupType === TaxonomicFilterGroupType.Events ||
        listGroupType === TaxonomicFilterGroupType.CustomEvents ||
        listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix) ? (
        <PropertyKeyInfo value={item.name ?? ''} disablePopover />
    ) : listGroupType === TaxonomicFilterGroupType.Elements ? (
        <PropertyKeyInfo type="element" value={item.name ?? ''} disablePopover />
    ) : (
        item.name ?? ''
    )
}

const renderItemPopup = (
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
                        <PropertyKeyInfo value={item.name ?? ''} />
                    </h3>
                    {item && <ActionSelectInfo entity={item as ActionType} />}
                </div>
            )
        }

        if (
            // NB: also update "selectedItemHasPopup" below
            listGroupType === TaxonomicFilterGroupType.Events ||
            listGroupType === TaxonomicFilterGroupType.EventProperties ||
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
                    <PropertyKeyDescription data={data} value={value.toString()} />

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
    item?: PropertyDefinition | CohortType,
    listGroupType?: TaxonomicFilterGroupType,
    group?: TaxonomicFilterGroup
): boolean => {
    return (
        // NB: also update "renderItemPopup" above
        !!item &&
        !!group?.getValue(item) &&
        (listGroupType === TaxonomicFilterGroupType.Actions ||
            ((listGroupType === TaxonomicFilterGroupType.Elements ||
                listGroupType === TaxonomicFilterGroupType.Events ||
                listGroupType === TaxonomicFilterGroupType.EventProperties ||
                listGroupType === TaxonomicFilterGroupType.PersonProperties) &&
                !!getKeyMapping(
                    group?.getValue(item),
                    listGroupType === TaxonomicFilterGroupType.Elements ? 'element' : 'event'
                )))
    )
}

export function InfiniteList(): JSX.Element {
    const { mouseInteractionsEnabled, activeTab, searchQuery, value, groupType } = useValues(taxonomicFilterLogic)
    const { selectItem } = useActions(taxonomicFilterLogic)

    const { isLoading, results, totalCount, index, listGroupType, group, selectedItem, selectedItemInView } =
        useValues(infiniteListLogic)
    const { onRowsRendered, setIndex } = useActions(infiniteListLogic)

    const isActiveTab = listGroupType === activeTab
    const showEmptyState = totalCount === 0 && !isLoading

    const [referenceElement, setReferenceElement] = useState<HTMLDivElement | null>(null)
    const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null)

    const { styles, attributes } = usePopper(referenceElement, popperElement, {
        placement: 'right',
        modifiers: [
            {
                name: 'offset',
                options: {
                    offset: [0, 10],
                },
            },
        ],
    })

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const item = results[rowIndex]
        const itemValue = item ? group?.getValue?.(item) : null
        const isSelected = listGroupType === groupType && itemValue === value
        const isHighlighted = rowIndex === index && isActiveTab

        return item && group ? (
            <div
                key={`item_${rowIndex}`}
                className={`taxonomic-list-row${rowIndex === index ? ' hover' : ''}${isSelected ? ' selected' : ''}`}
                onClick={() => selectItem(group, itemValue ?? null, item)}
                onMouseOver={() => (mouseInteractionsEnabled ? setIndex(rowIndex) : null)}
                style={style}
                data-attr={`prop-filter-${listGroupType}-${rowIndex}`}
                ref={isHighlighted ? setReferenceElement : null}
            >
                {renderItemContents({ item, listGroupType })}
            </div>
        ) : (
            <div
                key={`skeleton_${rowIndex}`}
                className={`taxonomic-list-row skeleton-row${rowIndex === index ? ' hover' : ''}`}
                onMouseOver={() => mouseInteractionsEnabled && setIndex(rowIndex)}
                style={style}
                data-attr={`prop-skeleton-${listGroupType}-${rowIndex}`}
            >
                <Skeleton active title={false} paragraph={{ rows: 1 }} />
            </div>
        )
    }

    return (
        <div className={`taxonomic-infinite-list${showEmptyState ? ' empty-infinite-list' : ''}`}>
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
                            rowCount={isLoading && totalCount === 0 ? 7 : totalCount}
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
            selectedItemHasPopup(selectedItem, listGroupType, group) &&
            tooltipDesiredState(referenceElement) !== ListTooltip.None
                ? ReactDOM.createPortal(
                      <div
                          className="popper-tooltip click-outside-block Popup"
                          ref={setPopperElement}
                          style={styles.popper}
                          {...attributes.popper}
                      >
                          {selectedItem && group ? renderItemPopup(selectedItem, listGroupType, group) : null}
                      </div>,
                      document.querySelector('body') as HTMLElement
                  )
                : null}
        </div>
    )
}
