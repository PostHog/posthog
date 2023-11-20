import React from 'react'
import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { actionBarLogic } from './actionBarLogic'
import { IconChevronRight, IconEdit } from 'lib/lemon-ui/icons'
import { CommandFlow } from 'lib/components/CommandPalette/commandPaletteLogic'

type PrefixIconProps = {
    activeFlow: CommandFlow | null
}
const PrefixIcon = ({ activeFlow }: PrefixIconProps): React.ReactElement | null => {
    if (activeFlow) {
        return <activeFlow.icon className="palette__icon" /> ?? <IconEdit className="palette__icon" />
    } else {
        return <IconChevronRight className="palette__icon" />
    }
}

export const ActionInput = (): JSX.Element => {
    const { input, activeFlow } = useValues(actionBarLogic)
    const { setInput } = useActions(actionBarLogic)

    return (
        <div className="border-b">
            <LemonInput
                size="small"
                className="CommandBar__input"
                fullWidth
                prefix={<PrefixIcon activeFlow={activeFlow} />}
                suffix={<KeyboardShortcut escape muted />}
                placeholder={activeFlow?.instruction ?? 'What would you like to do? Try some suggestions…'}
                autoFocus
                value={input}
                onChange={setInput}
            />
        </div>
    )
}
