import { useValues, useActions } from 'kea'
import { commandPaletteLogic } from './commandPaletteLogic'
import { IconEdit, IconExclamation, IconMagnifier } from 'lib/lemon-ui/icons'

export function CommandInput(): JSX.Element {
    const { input, isSqueak, activeFlow } = useValues(commandPaletteLogic)
    const { setInput } = useActions(commandPaletteLogic)

    return (
        <div className="palette__row">
            {isSqueak ? (
                <IconExclamation className="palette__icon" />
            ) : activeFlow ? (
                <activeFlow.icon className="palette__icon" /> ?? <IconEdit className="palette__icon" />
            ) : (
                <IconMagnifier className="palette__icon" />
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
