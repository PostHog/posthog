import React, { useState } from 'react'
import { AnyPropertyFilter } from '~/types'
import { Button } from 'antd'
import { Row } from 'antd'
import { PropertyFilterButton } from './PropertyFilterButton'
import { isValidPathCleanFilter, isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { Popup } from 'lib/components/Popup/Popup'
import { PlusCircleOutlined } from '@ant-design/icons'
import '../../../../scenes/actions/Actions.scss' // TODO: we should decouple this styling from this component sooner than later
import './FilterRow.scss'
import clsx from 'clsx'
import { IconDelete, IconPlus } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { CloseButton } from 'lib/components/CloseButton'

interface FilterRowProps {
    item: Record<string, any>
    index: number
    filters: AnyPropertyFilter[]
    pageKey: string
    showConditionBadge?: boolean
    totalCount: number
    disablePopover?: boolean
    filterComponent: (onComplete: () => void) => JSX.Element
    label: string
    onRemove: (index: number) => void
    orFiltering?: boolean
    useLemonButton?: boolean // To be removed once lemon is completely released
}

export const FilterRow = React.memo(function FilterRow({
    item,
    index,
    filters,
    pageKey,
    showConditionBadge,
    totalCount,
    disablePopover = false, // use bare PropertyFilter without popover
    filterComponent,
    label,
    onRemove,
    orFiltering,
    useLemonButton = false,
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
            className={clsx(
                'property-filter-row',
                !disablePopover && 'wrap-filters',
                orFiltering && index !== 0 && 'mt-05'
            )}
            data-attr={'property-filter-' + index}
            wrap={false}
        >
            {disablePopover ? (
                <>
                    {filterComponent(() => setOpen(false))}
                    {!!Object.keys(filters[index]).length &&
                        (orFiltering ? (
                            <LemonButton
                                icon={<IconDelete />}
                                type="alt"
                                onClick={() => onRemove(index)}
                                size="small"
                            />
                        ) : (
                            <CloseButton
                                onClick={() => onRemove(index)}
                                style={{
                                    cursor: 'pointer',
                                    float: 'none',
                                    paddingLeft: 8,
                                    paddingTop: 4,
                                }}
                            />
                        ))}
                </>
            ) : (
                <Popup
                    className={'filter-row-popup'}
                    visible={open}
                    onClickOutside={() => handleVisibleChange(false)}
                    overlay={filterComponent(() => setOpen(false))}
                >
                    {isValidPropertyFilter(item) ? (
                        <PropertyFilterButton
                            onClick={() => setOpen(!open)}
                            onClose={() => onRemove(index)}
                            item={item}
                        />
                    ) : isValidPathCleanFilter(item) ? (
                        <PropertyFilterButton
                            item={item}
                            onClick={() => setOpen(!open)}
                            onClose={() => onRemove(index)}
                        >
                            {`${item['alias']}::${item['regex']}`}
                        </PropertyFilterButton>
                    ) : useLemonButton ? (
                        <LemonButton
                            onClick={() => setOpen(!open)}
                            className="new-prop-filter"
                            data-attr={'new-prop-filter-' + pageKey}
                            type="secondary"
                            size="small"
                            icon={<IconPlus style={{ color: 'var(--primary)' }} />}
                        >
                            {label}
                        </LemonButton>
                    ) : (
                        <Button
                            onClick={() => setOpen(!open)}
                            className="new-prop-filter"
                            data-attr={'new-prop-filter-' + pageKey}
                            style={{
                                color: 'var(--primary)',
                                border: 'none',
                                boxShadow: 'none',
                                paddingLeft: 0,
                                background: 'none',
                            }}
                            icon={<PlusCircleOutlined />}
                            type="default"
                        >
                            {label}
                        </Button>
                    )}
                </Popup>
            )}
            {key && showConditionBadge && index + 1 < totalCount && (
                <span style={{ marginLeft: 16, right: 16, position: 'absolute' }} className="stateful-badge and">
                    AND
                </span>
            )}
        </Row>
    )
})
