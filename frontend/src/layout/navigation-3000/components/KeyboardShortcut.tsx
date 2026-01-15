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
    delete: '⌫',
}
/** For consistency, we always show modifiers in this order, before other keys. */
const MODIFIER_PRIORITY: HotKeyOrModifier[] = ['command', 'option', 'shift']

export interface KeyboardShortcutProps extends Partial<Record<HotKeyOrModifier, true>> {
    className?: string
    /** If true, keys are displayed in the order they're passed instead of sorted */
    preserveOrder?: boolean
    /** If true, the keyboard shortcut is displayed in a minimal style */
    minimal?: boolean
}

export function KeyboardShortcut({
    className,
    preserveOrder,
    minimal,
    ...keys
}: KeyboardShortcutProps): JSX.Element | null {
    const keyList = Object.keys(keys) as HotKeyOrModifier[]

    const sortedKeys = preserveOrder
        ? keyList
        : keyList.sort((a, b) => {
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
          })

    if (isMobile()) {
        // If the user agent says we're on mobile, then it's unlikely - though of course not impossible -
        // that there's a physical keyboard. Hence in that case we don't show the keyboard shortcut
        return null
    }

    return (
        <kbd
            className={cn(
                'KeyboardShortcut gap-x-0.5',
                minimal && 'bg-transparent border-none text-tertiary dark:text-secondary opacity-75',
                className
            )}
        >
            {sortedKeys.map((key) => (
                <span key={key}>{KEY_TO_SYMBOL[key] || key}</span>
            ))}
        </kbd>
    )
}
