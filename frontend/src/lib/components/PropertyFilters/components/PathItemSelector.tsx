import React, { useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { SimpleOption, TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

interface PathItemSelectorProps {
    pathItem: TaxonomicFilterValue | undefined
    onChange: (item: string) => void
    children: JSX.Element
    index: number
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    disabled?: boolean
    wildcardOptions?: SimpleOption[]
}

export function PathItemSelector({
    pathItem,
    onChange,
    children,
    taxonomicGroupTypes,
    disabled,
    wildcardOptions,
}: PathItemSelectorProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    return (
        <Popup
            visible={visible}
            placement={'bottom-end'}
            fallbackPlacements={['bottom-start']}
            onClickOutside={() => setVisible(false)}
            overlay={
                <TaxonomicFilter
                    groupType={TaxonomicFilterGroupType.PageviewUrls}
                    value={pathItem}
                    onChange={(_, value) => {
                        onChange(value as string)
                        setVisible(false)
                    }}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                    optionsFromProp={{ wildcard: wildcardOptions }}
                />
            }
        >
            {({ setRef }) => {
                return (
                    <div ref={setRef} onClick={disabled ? () => {} : () => setVisible(!visible)}>
                        {children}
                    </div>
                )
            }}
        </Popup>
    )
}
