import { IconX } from '@posthog/icons'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { useEffect, useState } from 'react'

import { AnyDataNode } from '~/queries/schema'

export interface TaxonomicPopoverProps<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>
    extends Omit<LemonButtonProps, 'children' | 'onClick' | 'sideIcon' | 'sideAction'> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType
    onChange: (value: ValueType, groupType: TaxonomicFilterGroupType, item: any) => void

    groupTypes?: TaxonomicFilterGroupType[]
    renderValue?: (value: ValueType) => JSX.Element | null
    eventNames?: string[]
    placeholder?: React.ReactNode
    placeholderClass?: string
    dropdownMatchSelectWidth?: boolean
    allowClear?: boolean
    style?: React.CSSProperties
    excludedProperties?: { [key in TaxonomicFilterGroupType]?: TaxonomicFilterValue[] }
    metadataSource?: AnyDataNode
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

export function TaxonomicPopover<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>({
    groupType,
    value,
    onChange,
    renderValue,
    groupTypes,
    eventNames = [],
    placeholder = 'Please select',
    placeholderClass = 'text-muted',
    allowClear = false,
    excludedProperties,
    metadataSource,
    ...buttonPropsRest
}: TaxonomicPopoverProps<ValueType>): JSX.Element {
    const [localValue, setLocalValue] = useState<ValueType>(value || ('' as ValueType))
    const [visible, setVisible] = useState(false)

    const isClearButtonShown = allowClear && !!localValue

    const buttonPropsFinal: Omit<LemonButtonProps, 'sideIcon' | 'sideAction'> = buttonPropsRest
    buttonPropsFinal.children = localValue ? (
        <span>{renderValue?.(localValue) ?? localValue}</span>
    ) : (
        <span className={placeholderClass ?? 'text-muted'}>{placeholder}</span>
    )
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
                    onChange={({ type }, payload, item) => {
                        onChange?.(payload as ValueType, type, item)
                        setVisible(false)
                    }}
                    taxonomicGroupTypes={groupTypes ?? [groupType]}
                    eventNames={eventNames}
                    metadataSource={metadataSource}
                    excludedProperties={excludedProperties}
                />
            }
            sameWidth={false}
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
                />
            ) : (
                <LemonButton {...buttonPropsFinal} />
            )}
        </LemonDropdown>
    )
}
