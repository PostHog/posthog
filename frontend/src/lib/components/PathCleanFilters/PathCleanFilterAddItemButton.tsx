import { useState } from 'react'

import { PathCleaningFilter } from '~/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconPlus } from 'lib/lemon-ui/icons'

import { PathRegexPopover } from './PathRegexPopover'

type PathCleanFilterAddItemButtonProps = {
    onAdd: (filter: PathCleaningFilter) => void
}

export function PathCleanFilterAddItemButton({ onAdd }: PathCleanFilterAddItemButtonProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            overlay={
                <PathRegexPopover
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
        </Popover>
    )
}
