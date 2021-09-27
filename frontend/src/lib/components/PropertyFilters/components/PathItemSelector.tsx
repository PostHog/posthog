import React, { useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface PathItemSelectorProps {
    pathItem: string | undefined | null
    onChange: (item: string) => void
    children: JSX.Element
    index: number
    groupTypes?: TaxonomicFilterGroupType[]
}

export function PathItemSelector({ pathItem, onChange, children, groupTypes }: PathItemSelectorProps): JSX.Element {
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
                    groupTypes={groupTypes}
                />
            }
        >
            {({ setRef }) => {
                return (
                    <div ref={setRef} onClick={() => setVisible(!visible)}>
                        {children}
                    </div>
                )
            }}
        </Popup>
    )
}
