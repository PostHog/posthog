import './KeyboardShortcut.scss'

import clsx from 'clsx'

import { isMac, isMobile } from 'lib/utils'

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
    className?: string
}

export function KeyboardShortcut({ className, ...keys }: KeyboardShortcutProps): JSX.Element | null {
    const sortedKeys = Object.keys(keys).sort(
        (a, b) =>
            (-MODIFIER_PRIORITY.indexOf(a as HotKeyOrModifier) || 0) -
            (-MODIFIER_PRIORITY.indexOf(b as HotKeyOrModifier) || 0)
    ) as HotKeyOrModifier[]

    if (isMobile()) {
        // If the user agent says we're on mobile, then it's unlikely - though of course not impossible -
        // that there's a physical keyboard. Hence in that case we don't show the keyboard shortcut
        return null
    }

    return (
        <kbd className={clsx('KeyboardShortcut gap-x-0.5', className)}>
            {sortedKeys.map((key) => (
                <span key={key}>{KEY_TO_SYMBOL[key] || key}</span>
            ))}
        </kbd>
    )
}
