import { isMac } from 'lib/utils'
import { HotKeyOrModifier } from '~/types'
import './KeyboardShortcut.scss'

type KeyboardShortcutProps = Partial<Record<HotKeyOrModifier, true>>

export function KeyboardShortcut(props: KeyboardShortcutProps): JSX.Element {
    const useMacSymbols = isMac()

    return (
        <span className="KeyboardShortcut">
            {'shift' in props && props.shift && <span className="KeyboardShortcut__key">⇧</span>}
            {'command' in props && props.command && (
                <span className="KeyboardShortcut__key">{useMacSymbols ? '⌘' : 'Ctrl'}</span>
            )}
            {'option' in props && props.option && (
                <span className="KeyboardShortcut__key">{useMacSymbols ? '⌥' : 'Alt'}</span>
            )}
            {Object.keys(props)
                .filter((key) => !['shift', 'command', 'option'].includes(key))
                .map((key) => (
                    <span key={key} className="KeyboardShortcut__key">
                        {key}
                    </span>
                ))}
        </span>
    )
}
