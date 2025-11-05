import { useState } from 'react'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { PathCleaningFilter } from '~/types'

import { PathRegexModal } from './PathRegexModal'

type PathCleanFilterAddItemButtonProps = {
    onAdd: (filter: PathCleaningFilter) => void
}

export function PathCleanFilterAddItemButton({ onAdd }: PathCleanFilterAddItemButtonProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    return (
        <>
            <PathRegexModal
                isOpen={visible}
                onClose={() => setVisible(false)}
                onSave={(filter: PathCleaningFilter) => {
                    onAdd(filter)
                    setVisible(false)
                }}
            />

            <LemonButton
                onClick={() => setVisible(true)}
                type="secondary"
                size="small"
                icon={<IconPlus />}
                sideIcon={null}
            >
                Add rule
            </LemonButton>
        </>
    )
}
