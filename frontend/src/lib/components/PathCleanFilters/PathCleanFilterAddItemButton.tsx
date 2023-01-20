import { useState } from 'react'

import { PathCleaningFilter } from '~/types'
import { Popup } from 'lib/components/Popup/Popup'
import { LemonButton } from 'lib/components/LemonButton'
import { IconPlus } from 'lib/components/icons'

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
            overlay={<PathRegexPopup onSave={onAdd} onCancel={() => setVisible(false)} isNew />}
        >
            <LemonButton onClick={() => setVisible(!visible)} type="secondary" size="small" icon={<IconPlus />}>
                Add rule
            </LemonButton>
        </Popup>
    )
}
