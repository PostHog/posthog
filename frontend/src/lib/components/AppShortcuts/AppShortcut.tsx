import { useMergeRefs } from '@floating-ui/react'
import { ReactElement, cloneElement, forwardRef, isValidElement } from 'react'

import { cn } from 'lib/utils/css-classes'

import { RenderKeybind } from './AppShortcutMenu'
import { AppShortcutType } from './appShortcutLogic'
import { convertPlatformKeybind, useAppShortcut } from './useAppShortcut'

export function keybindToKeyboardShortcutProps(keybind: string[]): Record<string, boolean> {
    const platformAgnosticKeybind = convertPlatformKeybind(keybind)
    return Object.fromEntries(platformAgnosticKeybind.map((key) => [key, true]))
}

interface AppShortcutProps extends Omit<AppShortcutType, 'ref' | 'keybind' | 'interaction' | 'callback'> {
    /** The keybind(s) to use for the shortcut - can be a single keybind or multiple alternative keybinds */
    keybind: string[][]
    /** Single React element child - must forward ref to clickable/focusable element */
    children: ReactElement
    /** 'click' triggers element.click(), 'focus' triggers element.focus(), doesn't support `function` which should use `useAppShortcut` directly instead */
    interaction: 'click' | 'focus'
    /** If true, the keyboard shortcut will not be registered and tooltip keyboard shortcut will not be added to the childs tooltip */
    disabled?: boolean
}

// forwardRef is needed so parent components (e.g. Popover) can inject refs through AppShortcut to the child element
export const AppShortcut = forwardRef<HTMLElement, AppShortcutProps>(function AppShortcut(
    { children, name, keybind, intent, interaction, scope = 'global', disabled = false, priority = 0 },
    forwardedRef
): ReactElement {
    const { callbackRef } = useAppShortcut({
        name,
        keybind,
        intent,
        interaction,
        scope,
        disabled,
        priority,
    })

    const mergedRef = useMergeRefs([callbackRef, forwardedRef])

    if (!isValidElement(children)) {
        throw new Error('AppShortcut requires a single React element child')
    }

    const childProps = children.props as Record<string, unknown>
    const keybindStrings = keybind.map((kb) => kb.join('+')).join(',')

    // Append keyboard shortcut to tooltip if child has one
    let finalTooltip = childProps.tooltip
    if (childProps.tooltip && !disabled) {
        finalTooltip = (
            <>
                {childProps.tooltip}{' '}
                {keybind.map((kb, index) => (
                    <span key={index}>
                        {index > 0 && <span className="text-xs opacity-75"> or </span>}
                        <RenderKeybind keybind={[kb]} className="relative text-xs -top-px" />
                    </span>
                ))}
            </>
        )
    }

    return cloneElement(children, {
        ref: mergedRef,
        'data-shortcut-name': name,
        'data-shortcut-keybind': keybindStrings,
        'data-shortcut-intent': intent,
        'aria-keyshortcuts': keybindStrings,
        tooltip: finalTooltip,
        className: cn(childProps.className as string | undefined),
    } as Record<string, unknown>)
})
