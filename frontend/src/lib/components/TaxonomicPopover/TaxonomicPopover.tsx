import { IconX } from '@posthog/icons'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    DataWarehousePopoverField,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { forwardRef, Ref, useEffect, useState } from 'react'
import { LocalFilter } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'

export interface TaxonomicPopoverProps<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>
    extends Omit<LemonButtonProps, 'children' | 'onClick' | 'sideIcon' | 'sideAction'> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType | null
    onChange: (value: ValueType, groupType: TaxonomicFilterGroupType, item: any) => void

    filter?: LocalFilter
    groupTypes?: TaxonomicFilterGroupType[]
    renderValue?: (value: ValueType) => JSX.Element | null
    eventNames?: string[]
    placeholder?: React.ReactNode
    placeholderClass?: string
    /** Width of the popover. */
    width?: number
    schemaColumns?: DatabaseSchemaField[]
    allowClear?: boolean
    style?: React.CSSProperties
    excludedProperties?: { [key in TaxonomicFilterGroupType]?: TaxonomicFilterValue[] }
    metadataSource?: AnyDataNode
    showNumericalPropsOnly?: boolean
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
    maxContextOptions?: MaxContextTaxonomicFilterOption[]
}

/** Like TaxonomicPopover, but convenient when you know you will only use string values */
export function TaxonomicStringPopover(props: TaxonomicPopoverProps<string>): JSX.Element {
    return (
        <TaxonomicPopover
            {...props}
            value={String(props.value)}
            onChange={(value, groupType, item) => props.onChange?.(String(value), groupType, item)}
            renderValue={(value) => props.renderValue?.(String(value)) ?? <>{String(props.value)}</>}
        />
    )
}

export const TaxonomicPopover = forwardRef(function TaxonomicPopover_<
    ValueType extends TaxonomicFilterValue = TaxonomicFilterValue
>(
    {
        groupType,
        value,
        filter,
        onChange,
        renderValue,
        groupTypes,
        eventNames = [],
        placeholder = 'Please select',
        placeholderClass,
        allowClear = false,
        excludedProperties,
        metadataSource,
        schemaColumns,
        showNumericalPropsOnly,
        dataWarehousePopoverFields,
        maxContextOptions,
        width,
        ...buttonPropsRest
    }: TaxonomicPopoverProps<ValueType>,
    ref: Ref<HTMLButtonElement>
): JSX.Element {
    const [localValue, setLocalValue] = useState<ValueType>(value || ('' as ValueType))
    const [visible, setVisible] = useState(false)

    const isClearButtonShown = allowClear && !!localValue

    const buttonPropsFinal: Omit<LemonButtonProps, 'sideIcon' | 'sideAction'> = buttonPropsRest
    buttonPropsFinal.children = localValue ? (
        <span>{renderValue?.(localValue) ?? localValue}</span>
    ) : placeholder || placeholderClass ? (
        <span className={placeholderClass ?? 'text-muted'}>{placeholder}</span>
    ) : null
    buttonPropsFinal.onClick = () => setVisible(!visible)
    if (!buttonPropsFinal.type) {
        buttonPropsFinal.type = 'secondary'
    }

    useEffect(() => {
        if (!buttonPropsFinal.loading) {
            setLocalValue(value || ('' as ValueType))
        }
    }, [value])

    return (
        <LemonDropdown
            overlay={
                <TaxonomicFilter
                    groupType={groupType}
                    value={value}
                    filter={filter}
                    onChange={({ type }, payload, item) => {
                        onChange?.(payload as ValueType, type, item)
                        setVisible(false)
                    }}
                    taxonomicGroupTypes={groupTypes ?? [groupType]}
                    eventNames={eventNames}
                    schemaColumns={schemaColumns}
                    metadataSource={metadataSource}
                    excludedProperties={excludedProperties}
                    showNumericalPropsOnly={showNumericalPropsOnly}
                    dataWarehousePopoverFields={dataWarehousePopoverFields}
                    maxContextOptions={maxContextOptions}
                    width={width}
                />
            }
            matchWidth={false}
            actionable
            visible={visible}
            onClickOutside={() => {
                setVisible(false)
            }}
        >
            {isClearButtonShown ? (
                <LemonButton
                    sideAction={{
                        icon: <IconX />,
                        tooltip: 'Clear selection',
                        onClick: (e) => {
                            e.stopPropagation()
                            onChange?.('' as ValueType, groupType, null)
                            setLocalValue('' as ValueType)
                        },
                        divider: false,
                    }}
                    {...buttonPropsFinal}
                    ref={ref}
                />
            ) : (
                <LemonButton {...buttonPropsFinal} ref={ref} />
            )}
        </LemonDropdown>
    )
}) as <ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>(
    p: TaxonomicPopoverProps<ValueType> & { ref?: Ref<HTMLButtonElement> }
) => JSX.Element
