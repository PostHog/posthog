import './TaxonomicPopup.scss'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useState } from 'react'
import { Button } from 'antd'
import { DownOutlined } from '@ant-design/icons'

export interface TaxonomicPopupProps {
    groupType: TaxonomicFilterGroupType
    value?: string
    onChange: (value: string, groupType: TaxonomicFilterGroupType) => void

    groupTypes?: TaxonomicFilterGroupType[]
    renderValue?: (value: string) => JSX.Element
    dataAttr?: string
    eventNames?: string[]
    placeholder?: React.ReactNode
    style?: React.CSSProperties
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
}: TaxonomicPopupProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <Popup
            overlay={
                <TaxonomicFilter
                    groupType={groupType}
                    value={value}
                    onChange={({ type }, payload) => {
                        onChange?.(String(payload), type)
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
                    onClick={() => setVisible(true)}
                    ref={setRef}
                    className="TaxonomicPopup__button"
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
