import { useState } from 'react'
import { Button } from 'antd'

import { PathCleaningFilter } from '~/types'
import { Popup } from 'lib/components/Popup/Popup'
import { CloseButton } from 'lib/components/CloseButton'
import { midEllipsis } from 'lib/utils'

import { PathRegexPopup } from './PathRegexPopup'

interface PathCleanFilterItem {
    filter: PathCleaningFilter
    onChange: (filter: PathCleaningFilter) => void
    onRemove: () => void
}

export function PathCleanFilterItem({ filter, onChange, onRemove }: PathCleanFilterItem): JSX.Element {
    const [visible, setVisible] = useState(false)
    const label = `${filter.alias}::${filter.regex}`

    return (
        <Popup
            visible={visible}
            onClickOutside={() => setVisible(false)}
            overlay={<PathRegexPopup filter={filter} onSave={onChange} onCancel={() => setVisible(false)} />}
        >
            <Button
                shape="round"
                onClick={() => {
                    setVisible(!visible)
                }}
                className="PropertyFilterButton"
            >
                <span className="PropertyFilterButton-content" title={label}>
                    {midEllipsis(label, 32)}
                </span>
                <CloseButton
                    onClick={() => {
                        onRemove()
                    }}
                />
            </Button>
        </Popup>
    )
}
