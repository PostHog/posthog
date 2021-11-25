import React, { useState } from 'react'
import { AnyPropertyFilter } from '~/types'
import { Button } from 'antd'
import { Row } from 'antd'
import { CloseButton } from 'lib/components/CloseButton'
import PropertyFilterButton, { FilterButton } from './PropertyFilterButton'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { isValidPathCleanFilter, isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { Popup } from 'lib/components/Popup/Popup'
import { PlusCircleOutlined } from '@ant-design/icons'
import '../../../../scenes/actions/Actions.scss' // TODO: we should decouple this styling from this component sooner than later
import './FilterRow.scss'
import { Placement } from '@popperjs/core'
import { ButtonType } from 'antd/lib/button'

interface FilterRowProps {
    item: Record<string, any>
    index: number
    filters: AnyPropertyFilter[]
    pageKey: string
    showConditionBadge?: boolean
    totalCount: number
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
    taxonomicPopoverPlacement?: Placement
    showNestedArrow?: boolean
    filterComponent: (onComplete: () => void) => JSX.Element
    label: string
    onRemove: (index: number) => void
    addButtonType?: ButtonType
    greyBadges?: boolean
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
    showNestedArrow = false,
    filterComponent,
    label,
    onRemove,
    greyBadges,
    addButtonType = 'link',
}: FilterRowProps) {
    const [open, setOpen] = useState(false)

    const { key } = item

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible && isValidPropertyFilter(item) && !item.key) {
            onRemove(index)
        }
        setOpen(visible)
    }

    return (
        <Row
            align="middle"
            className="property-filter-row mt-05 mb-05"
            data-attr={'property-filter-' + index}
            style={{
                width: '100%',
                margin: 0,
            }}
            wrap={false}
        >
            {disablePopover ? (
                <>
                    {filterComponent(() => setOpen(false))}
                    {!!Object.keys(filters[index]).length && (
                        <CloseButton
                            onClick={() => onRemove(index)}
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
                        overlay={filterComponent(() => setOpen(false))}
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
                                            greyBadges={greyBadges}
                                        />
                                    ) : isValidPathCleanFilter(item) ? (
                                        <FilterButton onClick={() => setOpen(!open)} setRef={setRef}>
                                            {`${item['alias']}::${item['regex']}`}
                                        </FilterButton>
                                    ) : (
                                        <Button
                                            ref={setRef}
                                            onClick={() => setOpen(!open)}
                                            className="new-prop-filter"
                                            data-attr={'new-prop-filter-' + pageKey}
                                            type={addButtonType}
                                            style={addButtonType === 'link' ? { paddingLeft: 0 } : undefined}
                                            icon={<PlusCircleOutlined />}
                                        >
                                            {label}
                                        </Button>
                                    )}
                                </>
                            )
                        }}
                    </Popup>
                    {!!Object.keys(filters[index]).length && (
                        <CloseButton
                            className="ml-1"
                            onClick={() => onRemove(index)}
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
