import './TaxonomicPopover.scss'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { useEffect, useState } from 'react'
import {
    LemonButton,
    LemonButtonProps,
    LemonButtonWithDropdown,
    LemonButtonWithDropdownProps,
} from 'lib/lemon-ui/LemonButton'
import { IconArrowDropDown, IconClose } from 'lib/lemon-ui/icons'

export interface TaxonomicPopoverProps<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>
    extends Omit<LemonButtonWithDropdownProps, 'dropdown' | 'value' | 'onChange' | 'placeholder'> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType
    onChange: (value: ValueType, groupType: TaxonomicFilterGroupType, item: any) => void

    groupTypes?: TaxonomicFilterGroupType[]
    renderValue?: (value: ValueType) => JSX.Element | null
    dataAttr?: string
    eventNames?: string[]
    placeholder?: React.ReactNode
    placeholderClass?: string
    dropdownMatchSelectWidth?: boolean
    allowClear?: boolean
    style?: React.CSSProperties
    buttonProps?: Omit<LemonButtonProps, 'onClick'>
    excludedProperties?: { [key in TaxonomicFilterGroupType]?: TaxonomicFilterValue[] }
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

export function TaxonomicPopover({
    groupType,
    value,
    onChange,
    renderValue,
    groupTypes,
    dataAttr,
    eventNames = [],
    placeholder = 'Please select',
    fullWidth = true,
    buttonProps,
}: TaxonomicPopoverProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <LemonButtonWithDropdown
            data-attr={dataAttr}
            status="stealth"
            dropdown={{
                onClickOutside: () => setVisible(false),
                overlay: (
                    <TaxonomicFilter
                        groupType={groupType}
                        value={value}
                        onChange={({ type }, payload, item) => {
                            onChange?.(payload, type, item)
                            setVisible(false)
                        }}
                        taxonomicGroupTypes={groupTypes ?? [groupType]}
                        eventNames={eventNames}
                    />
                ),
                visible: visible,
            }}
            onClick={() => setVisible(!visible)}
            fullWidth={fullWidth}
            type={'secondary'}
            {...buttonProps}
        >
            <span className="TaxonomicPopover__button__label truncate">
                {value ? renderValue?.(value) ?? String(value) : <em>{placeholder}</em>}
            </span>
            <div className="grow-1" />
        </LemonButtonWithDropdown>
    )
}

export function LemonTaxonomicPopover<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>({
    groupType,
    value,
    onChange,
    renderValue,
    groupTypes,
    dataAttr,
    eventNames = [],
    placeholder = 'Please select',
    placeholderClass = 'text-muted',
    allowClear = false,
    excludedProperties,
    ...buttonProps
}: TaxonomicPopoverProps<ValueType>): JSX.Element {
    const [localValue, setLocalValue] = useState<ValueType>(value || ('' as ValueType))
    const [visible, setVisible] = useState(false)

    const isClearButtonShown = allowClear && !!localValue

    useEffect(() => {
        if (!buttonProps.loading) {
            setLocalValue(value || ('' as ValueType))
        }
    }, [value])

    return (
        <div className="LemonButtonWithSideAction">
            {/* TODO: This is nasty. We embed a button in the sideicon which should be a big no-no.
            We should merge WithDropdown and WithSideaction as this is a common use case */}
            <LemonButtonWithDropdown
                className="TaxonomicPopover__button"
                data-attr={dataAttr}
                dropdown={{
                    overlay: (
                        <TaxonomicFilter
                            groupType={groupType}
                            value={value}
                            onChange={({ type }, payload, item) => {
                                onChange?.(payload as ValueType, type, item)
                                setVisible(false)
                            }}
                            taxonomicGroupTypes={groupTypes ?? [groupType]}
                            eventNames={eventNames}
                            excludedProperties={excludedProperties}
                        />
                    ),
                    sameWidth: false,
                    actionable: true,
                    visible,
                    onClickOutside: () => {
                        setVisible(false)
                    },
                }}
                onClick={() => {
                    setVisible(!visible)
                }}
                sideIcon={
                    <div className="flex">
                        {isClearButtonShown ? (
                            <LemonButton
                                className="side-buttons-row-button"
                                type="tertiary"
                                status="stealth"
                                icon={<IconClose style={{ fontSize: 16 }} />}
                                tooltip="Clear selection"
                                noPadding
                                onClick={(e) => {
                                    e.stopPropagation()
                                    onChange?.('' as ValueType, groupType, null)
                                    setLocalValue('' as ValueType)
                                }}
                            />
                        ) : (
                            <LemonButton
                                className="side-buttons-row-button side-buttons-row-button-no-hover"
                                type="tertiary"
                                status="stealth"
                                noPadding
                                icon={<IconArrowDropDown />}
                            />
                        )}
                    </div>
                }
                {...buttonProps}
            >
                {(localValue && (renderValue?.(localValue) ?? String(localValue))) || (
                    <span className={placeholderClass ?? 'text-muted'}>{placeholder}</span>
                )}
            </LemonButtonWithDropdown>
        </div>
    )
}
