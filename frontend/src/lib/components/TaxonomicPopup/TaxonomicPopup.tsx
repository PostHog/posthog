import './TaxonomicPopup.scss'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import React, { useEffect, useState } from 'react'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from 'lib/components/LemonButton'
import { IconArrowDropDown, IconClose } from 'lib/components/icons'
import clsx from 'clsx'
import { Button } from 'antd'
import { Popup } from 'lib/components/Popup/Popup'
import { DownOutlined } from '@ant-design/icons'

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
    style,
    fullWidth = true,
}: TaxonomicPopupProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <Popup
            overlay={
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
            }
            visible={visible}
            onClickOutside={() => setVisible(false)}
        >
            {({ setRef }) => (
                <Button
                    data-attr={dataAttr}
                    onClick={() => setVisible(!visible)}
                    ref={setRef}
                    className={clsx('TaxonomicPopup__button', { 'full-width': fullWidth })}
                    style={style}
                >
                    <span className="text-overflow" style={{ maxWidth: '100%' }}>
                        {value ? renderValue?.(value) ?? String(value) : <em>{placeholder}</em>}
                    </span>
                    <DownOutlined style={{ fontSize: 10 }} />
                </Button>
            )}
        </Popup>
    )
}

/** Like TaxonomicPopup, but convenient when you know you will only use string values */
export function LemonTaxonomicStringPopup(props: TaxonomicPopupProps<string>): JSX.Element {
    return (
        <LemonTaxonomicProps
            {...props}
            value={String(props.value)}
            onChange={(value, groupType) => props.onChange?.(String(value), groupType)}
            renderValue={(value) => props.renderValue?.(String(value)) ?? <>{String(props.value)}</>}
        />
    )
}

export function LemonTaxonomicProps({
    groupType,
    value,
    onChange,
    renderValue,
    groupTypes,
    dataAttr,
    eventNames = [],
    placeholder = 'Please select',
    style,
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
            <LemonButtonWithPopup
                data-attr={dataAttr}
                popup={{
                    overlay: (
                        <TaxonomicFilter
                            groupType={groupType}
                            value={value}
                            onChange={({ type }, payload) => {
                                onChange?.(payload, type)
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
                    <div className="side-buttons-row">
                        {isClearButtonShown && (
                            <>
                                <LemonButton
                                    className="side-buttons-row-button"
                                    type="tertiary"
                                    icon={<IconClose fontSize={16} />}
                                    tooltip="Clear selection"
                                    onClick={() => {
                                        onChange?.('', groupType)
                                        setLocalValue('')
                                    }}
                                />
                                <div className="side-buttons-row-button-divider" />
                            </>
                        )}
                        <LemonButton
                            className="side-buttons-row-button side-buttons-row-button-no-hover"
                            type="tertiary"
                            icon={<IconArrowDropDown />}
                        />
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
