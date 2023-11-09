import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { actionBarLogic } from './actionBarLogic'

const ActionInput = (): JSX.Element => {
    const { searchQuery } = useValues(actionBarLogic)
    const { setSearchQuery } = useActions(actionBarLogic)

    return (
        <div className="border-b">
            <LemonInput
                size="small"
                className="CommandBar__input"
                fullWidth
                suffix={<KeyboardShortcut escape muted />}
                autoFocus
                value={searchQuery}
                onChange={setSearchQuery}
            />
        </div>
    )
}

export default ActionInput
