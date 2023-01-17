import './TaxonomicPopup.scss'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { useEffect, useState } from 'react'
import {
    LemonButton,
    LemonButtonProps,
    LemonButtonWithPopup,
    LemonButtonWithPopupProps,
} from 'lib/components/LemonButton'
import { IconArrowDropDown, IconClose } from 'lib/components/icons'

export interface TaxonomicPopupProps<ValueType = TaxonomicFilterValue>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'value' | 'onChange' | 'placeholder'> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType
    onChange: (value: ValueType, groupType: TaxonomicFilterGroupType) => void

    groupTypes?: TaxonomicFilterGroupType[]
    renderValue?: (value: ValueType) => JSX.Element
    dataAttr?: string
    eventNames?: string[]
    placeholder?: React.ReactNode
    dropdownMatchSelectWidth?: boolean
    allowClear?: boolean
    style?: React.CSSProperties
    buttonProps?: Omit<LemonButtonProps, 'onClick'>
}

/** Like TaxonomicPopup, but convenient when you know you will only use string values */
export function TaxonomicStringPopup(props: TaxonomicPopupProps<string>): JSX.Element {
    return (
        <TaxonomicPopup
            {...props}
            value={String(props.value)}
            onChange={(value, groupType) => props.onChange?.(String(value), groupType)}
            renderValue={(value) => props.renderValue?.(String(value)) ?? <>{String(props.value)}</>}
        />
    )
}

export function TaxonomicPopup({
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
}: TaxonomicPopupProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <LemonButtonWithPopup
            data-attr={dataAttr}
            status="stealth"
            popup={{
                onClickOutside: () => setVisible(false),
                overlay: (
                    <TaxonomicFilter
                        groupType={groupType}
                        value={value}
                        onChange={({ type }, payload) => {
                            onChange?.(payload, type)
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
            <span className="TaxonomicPopup__button__label text-overflow">
                {value ? renderValue?.(value) ?? String(value) : <em>{placeholder}</em>}
            </span>
            <div style={{ flexGrow: 1 }} />
        </LemonButtonWithPopup>
    )
}

/** Like TaxonomicPopup, but convenient when you know you will only use string values */
export function LemonTaxonomicStringPopup(props: TaxonomicPopupProps<string>): JSX.Element {
    return (
        <LemonTaxonomicPopup
            {...props}
            value={String(props.value)}
            onChange={(value, groupType) => props.onChange?.(String(value), groupType)}
            renderValue={(value) => props.renderValue?.(String(value)) ?? <>{String(props.value)}</>}
        />
    )
}

export function LemonTaxonomicPopup({
    groupType,
    value,
    onChange,
    renderValue,
    groupTypes,
    dataAttr,
    eventNames = [],
    placeholder = 'Please select',
    allowClear = false,
    ...buttonProps
}: TaxonomicPopupProps): JSX.Element {
    const [localValue, setLocalValue] = useState<TaxonomicFilterValue>(value || '')
    const [visible, setVisible] = useState(false)

    const isClearButtonShown = allowClear && !!localValue

    useEffect(() => {
        if (!buttonProps.loading) {
            setLocalValue(value || '')
        }
    }, [value])

    return (
        <div className="LemonButtonWithSideAction">
            {/* TODO: This is nasty. We embed a button in the sideicon which should be a big no-no.
            We should merge WithPopup and WithSideaction as this is a common use case */}
            <LemonButtonWithPopup
                className="TaxonomicPopup__button"
                data-attr={dataAttr}
                popup={{
                    overlay: (
                        <TaxonomicFilter
                            groupType={groupType}
                            value={value}
                            onChange={({ type }, payload) => {
                                onChange?.(payload, type)
                                setVisible(false)
                            }}
                            taxonomicGroupTypes={groupTypes ?? [groupType]}
                            eventNames={eventNames}
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
                                    onChange?.('', groupType)
                                    setLocalValue('')
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
                    <span style={{ minWidth: '10rem' }} className="text-muted">
                        {placeholder}
                    </span>
                )}
            </LemonButtonWithPopup>
        </div>
    )
}
