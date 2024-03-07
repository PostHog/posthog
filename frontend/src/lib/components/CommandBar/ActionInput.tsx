import { IconPencil } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CommandFlow } from 'lib/components/CommandPalette/commandPaletteLogic'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { isMac } from 'lib/utils'
import React from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { actionBarLogic } from './actionBarLogic'

type PrefixIconProps = {
    activeFlow: CommandFlow | null
}

const PrefixIcon = ({ activeFlow }: PrefixIconProps): React.ReactElement | null => {
    if (activeFlow) {
        return <activeFlow.icon className="palette__icon" /> ?? <IconPencil className="palette__icon" />
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
                data-attr="action-bar-input"
                className="CommandBar__input"
                fullWidth
                prefix={<PrefixIcon activeFlow={activeFlow} />}
                suffix={<KeyboardShortcut escape />}
                placeholder={
                    activeFlow?.instruction ?? `Run a command… or press ${isMac() ? 'Delete' : 'Backspace'} for search`
                }
                autoFocus
                value={input}
                onChange={setInput}
            />
        </div>
    )
}
