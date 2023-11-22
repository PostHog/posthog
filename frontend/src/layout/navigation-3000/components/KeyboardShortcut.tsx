import './KeyboardShortcut.scss'

import clsx from 'clsx'
import { isMac } from 'lib/utils'

import { HotKeyOrModifier } from '~/types'

const IS_MAC = isMac()
const KEY_TO_SYMBOL: Partial<Record<HotKeyOrModifier, string>> = {
    shift: '⇧',
    command: IS_MAC ? '⌘' : 'ctrl',
    option: IS_MAC ? '⌥' : 'alt',
    arrowup: '↑',
    arrowdown: '↓',
    arrowleft: '←',
    arrowright: '→',
    enter: '↵',
    escape: 'esc',
    tab: '⇥',
    space: '␣',
    forwardslash: '/',
}
/** For consistency, we always show modifiers in this order, before other keys. */
const MODIFIER_PRIORITY: HotKeyOrModifier[] = ['shift', 'command', 'option']

export interface KeyboardShortcutProps extends Partial<Record<HotKeyOrModifier, true>> {
    /** Whether this shortcut should be shown with muted opacity. */
    muted?: boolean
}

export function KeyboardShortcut({ muted, ...keys }: KeyboardShortcutProps): JSX.Element {
    const sortedKeys = Object.keys(keys).sort(
        (a, b) =>
            (-MODIFIER_PRIORITY.indexOf(a as HotKeyOrModifier) || 0) -
            (-MODIFIER_PRIORITY.indexOf(b as HotKeyOrModifier) || 0)
    ) as HotKeyOrModifier[]

    return (
        <span
            className={clsx('KeyboardShortcut KeyboardShortcut__key space-x-0.5', muted && 'KeyboardShortcut--muted')}
        >
            {sortedKeys.map((key) => (
                <span key={key}>{KEY_TO_SYMBOL[key] || key}</span>
            ))}
        </span>
    )
}
