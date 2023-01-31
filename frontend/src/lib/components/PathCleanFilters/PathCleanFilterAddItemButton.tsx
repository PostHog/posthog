import { useState } from 'react'

import { PathCleaningFilter } from '~/types'
import { Popup } from 'lib/lemon-ui/Popup/Popup'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconPlus } from 'lib/lemon-ui/icons'

import { PathRegexPopup } from './PathRegexPopup'

type PathCleanFilterAddItemButtonProps = {
    onAdd: (filter: PathCleaningFilter) => void
}

export function PathCleanFilterAddItemButton({ onAdd }: PathCleanFilterAddItemButtonProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    return (
        <Popup
            visible={visible}
            onClickOutside={() => setVisible(false)}
            overlay={
                <PathRegexPopup
                    onSave={(filter: PathCleaningFilter) => {
                        onAdd(filter)
                        setVisible(false)
                    }}
                    onCancel={() => setVisible(false)}
                    isNew
                />
            }
        >
            <LemonButton onClick={() => setVisible(!visible)} type="secondary" size="small" icon={<IconPlus />}>
                Add rule
            </LemonButton>
        </Popup>
    )
}
