import './KeyboardShortcut.scss'

import { isMac, isMobile } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

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
const MODIFIER_PRIORITY: HotKeyOrModifier[] = ['command', 'option', 'shift']

export interface KeyboardShortcutProps extends Partial<Record<HotKeyOrModifier, true>> {
    className?: string
    minimal?: boolean
}

export function KeyboardShortcut({ className, minimal, ...keys }: KeyboardShortcutProps): JSX.Element | null {
    const sortedKeys = Object.keys(keys).sort((a, b) => {
        const aIndex = MODIFIER_PRIORITY.indexOf(a as HotKeyOrModifier)
        const bIndex = MODIFIER_PRIORITY.indexOf(b as HotKeyOrModifier)

        // Modifiers come first, in MODIFIER_PRIORITY order
        if (aIndex !== -1 && bIndex !== -1) {
            return aIndex - bIndex
        }
        if (aIndex !== -1 && bIndex === -1) {
            return -1 // a is a modifier, b is not
        }
        if (aIndex === -1 && bIndex !== -1) {
            return 1 // b is a modifier, a is not
        }

        // Both are non-modifiers, sort alphabetically
        return a.localeCompare(b)
    }) as HotKeyOrModifier[]

    if (isMobile()) {
        // If the user agent says we're on mobile, then it's unlikely - though of course not impossible -
        // that there's a physical keyboard. Hence in that case we don't show the keyboard shortcut
        return null
    }

    return (
        <kbd
            className={cn(
                'KeyboardShortcut gap-x-0.5',
                minimal && 'bg-transparent text-tertiary/80 border-secondary border-0 -mt-[2px]',
                className
            )}
        >
            {sortedKeys.map((key) => (
                <span key={key}>{KEY_TO_SYMBOL[key] || key}</span>
            ))}
        </kbd>
    )
}
