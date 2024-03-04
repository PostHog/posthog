import { IconPencil, IconSearch } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { IconExclamation } from 'lib/lemon-ui/icons'

import { commandPaletteLogic } from './commandPaletteLogic'

export function CommandInput(): JSX.Element {
    const { input, isSqueak, activeFlow } = useValues(commandPaletteLogic)
    const { setInput } = useActions(commandPaletteLogic)

    return (
        <div className="palette__row">
            {isSqueak ? (
                <IconExclamation className="palette__icon" />
            ) : activeFlow ? (
                <activeFlow.icon className="palette__icon" /> ?? <IconPencil className="palette__icon" />
            ) : (
                <IconSearch className="palette__icon" />
            )}
            <input
                className="palette__display palette__input ph-no-capture"
                autoFocus
                value={input}
                onChange={(event) => {
                    setInput(event.target.value)
                }}
                placeholder={activeFlow?.instruction ?? 'What would you like to do? Try some suggestions…'}
                data-attr="command-palette-input"
            />
        </div>
    )
}
