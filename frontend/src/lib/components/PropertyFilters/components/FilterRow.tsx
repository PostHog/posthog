import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { AnyPropertyFilter } from '~/types'
import { Button } from 'antd'
import { useActions } from 'kea'
import { Row } from 'antd'
import { CloseButton } from 'lib/components/CloseButton'
import PropertyFilterButton from './PropertyFilterButton'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PlusCircleOutlined } from '@ant-design/icons'
import 'scenes/actions/Actions.scss' // TODO: we should decouple this styling from this component sooner than later
import './FilterRow.scss'
import { Placement } from '@popperjs/core'

interface FilterRowProps {
    item: AnyPropertyFilter
    index: number
    filters: AnyPropertyFilter[]
    pageKey: string
    showConditionBadge?: boolean
    totalCount: number
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
    taxonomicPopoverPlacement?: Placement
    groupTypes?: TaxonomicFilterGroupType[]
    showNestedArrow?: boolean
}

export const FilterRow = React.memo(function FilterRow({
    item,
    index,
    filters,
    pageKey,
    showConditionBadge,
    totalCount,
    disablePopover = false, // use bare PropertyFilter without popover
    taxonomicPopoverPlacement = undefined,
    groupTypes,
    showNestedArrow = false,
}: FilterRowProps) {
    const { remove } = useActions(propertyFilterLogic)
    const [open, setOpen] = useState(false)

    const { key } = item

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible && isValidPropertyFilter(item) && !item.key) {
            remove(index)
        }
        setOpen(visible)
    }

    const propertyFilterCommonProps = {
        key: index,
        pageKey,
        index,
        onComplete: () => setOpen(false),
        selectProps: {},
        groupTypes,
    }

    return (
        <Row
            align="middle"
            className="property-filter-row mt-05 mb-05"
            data-attr={'property-filter-' + index}
            style={{
                width: '100%',
                margin: '0.25rem 0',
                padding: '0.25rem 0',
            }}
            wrap={false}
        >
            {disablePopover ? (
                <>
                    <PropertyFilter {...propertyFilterCommonProps} disablePopover={disablePopover} />
                    {!!Object.keys(filters[index]).length && (
                        <CloseButton
                            onClick={() => remove(index)}
                            style={{
                                cursor: 'pointer',
                                float: 'none',
                                paddingLeft: 8,
                                alignSelf: 'flex-start',
                                paddingTop: 4,
                            }}
                        />
                    )}
                </>
            ) : (
                <>
                    <Popup
                        visible={open}
                        placement={taxonomicPopoverPlacement || 'bottom-end'}
                        fallbackPlacements={['bottom-start']}
                        onClickOutside={() => handleVisibleChange(false)}
                        overlay={
                            <PropertyFilter
                                {...propertyFilterCommonProps}
                                disablePopover={disablePopover}
                                selectProps={{
                                    delayBeforeAutoOpen: 150,
                                    placement: pageKey === 'trends-filters' ? 'bottomLeft' : undefined,
                                }}
                            />
                        }
                    >
                        {({ setRef }) => {
                            return (
                                <>
                                    {showNestedArrow && (
                                        <div className="property-filter-button-spacing">
                                            {index === 0 ? <>&#8627;</> : ''}
                                        </div>
                                    )}
                                    {isValidPropertyFilter(item) ? (
                                        <PropertyFilterButton
                                            onClick={() => setOpen(!open)}
                                            item={item}
                                            setRef={setRef}
                                        />
                                    ) : (
                                        <Button
                                            ref={setRef}
                                            onClick={() => setOpen(!open)}
                                            className="new-prop-filter"
                                            data-attr={'new-prop-filter-' + pageKey}
                                            type="link"
                                            style={{ paddingLeft: 0 }}
                                            icon={<PlusCircleOutlined />}
                                        >
                                            Add filter
                                        </Button>
                                    )}
                                </>
                            )
                        }}
                    </Popup>
                    {!!Object.keys(filters[index]).length && (
                        <CloseButton
                            className="ml-1"
                            onClick={() => remove(index)}
                            style={{ cursor: 'pointer', float: 'none', marginLeft: 5 }}
                        />
                    )}
                </>
            )}
            {key && showConditionBadge && index + 1 < totalCount && (
                <span style={{ marginLeft: 16, right: 16, position: 'absolute' }} className="stateful-badge and">
                    AND
                </span>
            )}
        </Row>
    )
})
