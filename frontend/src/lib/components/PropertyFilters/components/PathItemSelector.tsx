import { useState } from 'react'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { SimpleOption, TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

interface PathItemSelectorProps {
    pathItem: TaxonomicFilterValue | undefined
    onChange: (item: string) => void
    children: JSX.Element
    index: number
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
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
        <Popover
            visible={visible}
            placement="bottom-end"
            onClickOutside={() => setVisible(false)}
            overlay={
                <TaxonomicFilter
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
            <div onClick={disabled ? () => {} : () => setVisible(!visible)}>{children}</div>
        </Popover>
    )
}
