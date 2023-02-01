import { useState } from 'react'

import { PathCleaningFilter } from '~/types'
import { LemonSnack } from '@posthog/lemon-ui'
import { Popup } from 'lib/lemon-ui/Popup/Popup'
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
            overlay={
                <PathRegexPopup
                    filter={filter}
                    onSave={(filter: PathCleaningFilter) => {
                        onChange(filter)
                        setVisible(false)
                    }}
                    onCancel={() => setVisible(false)}
                />
            }
        >
            {/* required for popup placement */}
            <div className="relative">
                <LemonSnack
                    type="pill"
                    onClick={() => {
                        setVisible(!visible)
                    }}
                    onClose={onRemove}
                >
                    <span title={label}>{midEllipsis(label, 32)}</span>
                </LemonSnack>
            </div>
        </Popup>
    )
}
