import React, { useState } from 'react'
import { LemonButtonWithPopupProps } from '../LemonButton'
import { TaxonomicFilterValue } from '../TaxonomicFilter/types'
import { SearchDefinitionTypes, UniversalSearchGroupType, UniversalSearchProps } from './types'
import { Popup } from 'lib/components/Popup/Popup'
import { UniversalSearch } from './UniversalSearch'
import { Input } from 'antd'
import clsx from 'clsx'
import { IconMagnifier } from '../icons'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { useValues } from 'kea'
import { universalSearchLogic } from './universalSearchLogic'

export interface UniversalSearchPopupProps<ValueType = TaxonomicFilterValue>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'value' | 'onChange' | 'placeholder'> {
    groupType: UniversalSearchGroupType
    value?: ValueType
    onChange: (value: ValueType, groupType: UniversalSearchGroupType, item: SearchDefinitionTypes) => void

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
    groupTypes,
    dataAttr,
    style,
    fullWidth = true,
}: UniversalSearchPopupProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    const { isSideBarShown } = useValues(navigationLogic)
    const universalSearchLogicProps: UniversalSearchProps = {
        groupType,
        value,
        onChange: ({ type }, payload, item) => {
            onChange?.(payload, type, item)
            setVisible(false)
        },
        searchGroupTypes: groupTypes ?? [groupType],
        optionsFromProp: undefined,
        popoverEnabled: true,
        selectFirstItem: true,
    }
    const logic = universalSearchLogic(universalSearchLogicProps)
    const { searchQuery, searchPlaceholder } = useValues(logic)

    return (
        <div className="universal-search">
            <Popup
                overlay={
                    <UniversalSearch
                        groupType={groupType}
                        value={value}
                        onChange={({ type }, payload, item) => {
                            onChange?.(payload, type, item)
                            setVisible(false)
                        }}
                        searchGroupTypes={groupTypes ?? [groupType]}
                    />
                }
                visible={visible}
                placement="right-start"
                fallbackPlacements={['bottom']}
                onClickOutside={() => setVisible(false)}
                modifier={{
                    name: 'offset',
                    options: {
                        offset: ({ placement }) => {
                            if (placement === 'right-start') {
                                return [-10, -249 - 243]
                            } else {
                                return []
                            }
                        },
                    },
                }}
            >
                {({ setRef }) => (
                    <div
                        data-attr={dataAttr}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()
                            setVisible(!visible)
                        }}
                        ref={setRef}
                        className={clsx(
                            { 'full-width': fullWidth },
                            '',
                            'SearchBox',
                            isSideBarShown && 'SearchBox--sidebar-shown'
                        )}
                        style={style}
                    >
                        <Input
                            style={{ flexGrow: 1, cursor: 'pointer', opacity: visible ? '0' : '1' }}
                            data-attr="universal-search-field"
                            placeholder={searchPlaceholder}
                            value={searchQuery}
                            prefix={<IconMagnifier className={clsx('magnifier-icon', 'magnifier-icon-active222')} />}
                        />
                    </div>
                )}
            </Popup>
        </div>
    )
}
