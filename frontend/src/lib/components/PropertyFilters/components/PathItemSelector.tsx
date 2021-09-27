import React, { useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface PathItemSelectorProps {
    pathItem: string | undefined | null
    onChange: (item: string) => void
    children: JSX.Element
    index: number
}

export function PathItemSelector({ pathItem, onChange, children }: PathItemSelectorProps): JSX.Element {
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
                    groupTypes={[
                        TaxonomicFilterGroupType.PageviewUrls,
                        TaxonomicFilterGroupType.Screens,
                        TaxonomicFilterGroupType.CustomEvents,
                    ]}
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
