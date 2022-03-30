import React, { useState } from 'react'
import { LemonButtonWithPopupProps } from '../LemonButton'
import { TaxonomicFilterValue } from '../TaxonomicFilter/types'
import { UniversalSearchGroupType } from './types'
import { Popup } from 'lib/components/Popup/Popup'
import { UniversalSearch } from './UniversalSearch'
import { Button } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import clsx from 'clsx'

export interface UniversalSearchPopupProps<ValueType = TaxonomicFilterValue>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'value' | 'onChange' | 'placeholder'> {
    groupType: UniversalSearchGroupType
    value?: ValueType
    onChange: (value: ValueType, groupType: UniversalSearchGroupType) => void

    groupTypes?: UniversalSearchGroupType[]
    renderValue?: (value: ValueType) => JSX.Element
    dataAttr?: string
    eventNames?: string[]
    placeholder?: React.ReactNode
    dropdownMatchSelectWidth?: boolean
    allowClear?: boolean
}

export function UniversalSearchPopup({
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
}: UniversalSearchPopupProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <Popup
            overlay={
                <UniversalSearch
                    groupType={groupType}
                    value={value}
                    onChange={({ type }, payload, item) => {
                        onChange?.(payload, type, item)
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
                    <div style={{ flexGrow: 1 }} />
                    <DownOutlined style={{ fontSize: 10 }} />
                </Button>
            )}
        </Popup>
    )
}
