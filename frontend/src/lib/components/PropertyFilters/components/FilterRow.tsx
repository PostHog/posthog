import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { AnyPropertyFilter } from '~/types'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { Popover, Row } from 'antd'
import { CloseButton } from 'lib/components/CloseButton'
import PropertyFilterButton from './PropertyFilterButton'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PlusCircleOutlined } from '@ant-design/icons'
import 'scenes/actions/Actions.scss' // TODO: we should decouple this styling from this component sooner than later
import './FilterRow.scss'

interface FilterRowProps {
    item: AnyPropertyFilter
    index: number
    filters: AnyPropertyFilter[]
    pageKey: string
    showConditionBadge?: boolean
    totalCount: number
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
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
    popoverPlacement,
    groupTypes,
    showNestedArrow = false,
}: FilterRowProps) {
    const { remove } = useActions(propertyFilterLogic)
    const { featureFlags } = useValues(featureFlagLogic)
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

    const filterVariant = featureFlags[FEATURE_FLAGS.TAXONOMIC_PROPERTY_FILTER]
        ? 'taxonomic'
        : disablePopover
        ? 'unified'
        : 'tabs'

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
                    <PropertyFilter
                        {...propertyFilterCommonProps}
                        disablePopover={disablePopover}
                        variant={filterVariant}
                    />
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
            ) : filterVariant === 'taxonomic' ? (
                <>
                    <Popup
                        visible={open}
                        placement={'bottom-end'}
                        fallbackPlacements={['bottom-start']}
                        onClickOutside={() => handleVisibleChange(false)}
                        overlay={
                            <PropertyFilter
                                {...propertyFilterCommonProps}
                                disablePopover={disablePopover}
                                variant={filterVariant}
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
            ) : (
                <>
                    <Popover
                        trigger="click"
                        onVisibleChange={handleVisibleChange}
                        destroyTooltipOnHide={true}
                        defaultVisible={false}
                        visible={open}
                        placement={popoverPlacement || 'bottomLeft'}
                        getPopupContainer={(trigger) =>
                            // Prevent scrolling up on trigger
                            (trigger.parentNode as HTMLElement | undefined) ||
                            (document.querySelector('body') as HTMLElement)
                        }
                        content={
                            <PropertyFilter
                                {...propertyFilterCommonProps}
                                disablePopover={disablePopover}
                                variant={filterVariant}
                                selectProps={{
                                    delayBeforeAutoOpen: 150,
                                    placement: pageKey === 'trends-filters' ? 'bottomLeft' : undefined,
                                }}
                            />
                        }
                    >
                        {isValidPropertyFilter(item) ? (
                            <PropertyFilterButton onClick={() => setOpen(!open)} item={item} />
                        ) : (
                            <Button
                                type="link"
                                data-attr={'new-prop-filter-' + pageKey}
                                style={{ paddingLeft: 0 }}
                                icon={<PlusCircleOutlined />}
                            >
                                Add filter
                            </Button>
                        )}
                    </Popover>
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
