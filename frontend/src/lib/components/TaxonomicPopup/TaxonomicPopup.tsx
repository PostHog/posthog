import './TaxonomicPopup.scss'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import React, { useState } from 'react'
import { Button } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import clsx from 'clsx'

export interface TaxonomicPopupProps<ValueType = TaxonomicFilterValue> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType
    onChange: (value: ValueType, groupType: TaxonomicFilterGroupType) => void

    groupTypes?: TaxonomicFilterGroupType[]
    renderValue?: (value: ValueType) => JSX.Element
    dataAttr?: string
    eventNames?: string[]
    placeholder?: React.ReactNode
    style?: React.CSSProperties
    fullWidth?: boolean
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
