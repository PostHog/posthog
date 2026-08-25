import { useMergeRefs } from '@floating-ui/react'
import { ReactElement, cloneElement, forwardRef, isValidElement } from 'react'

import { cn } from 'lib/utils/css-classes'

import { ShortcutType } from './shortcutLogic'
import { RenderKeybind } from './ShortcutMenu'
import { convertPlatformKeybind, useShortcut } from './useShortcut'

export function keybindToKeyboardShortcutProps(keybind: string[]): Record<string, boolean> {
    const platformAgnosticKeybind = convertPlatformKeybind(keybind)
    return Object.fromEntries(platformAgnosticKeybind.map((key) => [key, true]))
}

interface ShortcutProps extends Omit<ShortcutType, 'ref' | 'keybind' | 'interaction' | 'callback'> {
    /** The keybind(s) to use for the shortcut - can be a single keybind or multiple alternative keybinds */
    keybind: string[][]
    /** Single React element child - must forward ref to clickable/focusable element */
    children: ReactElement
    /** 'click' triggers element.click(), 'focus' triggers element.focus(), doesn't support `function` which should use `useShortcut` directly instead */
    interaction: 'click' | 'focus'
    /**
     * If true, the keyboard shortcut is not registered and the keybind hint is not added to the child's tooltip.
     * Named `disableShortcut` rather than `disabled` so it does not collide with the `disabled` prop that wrappers
     * such as `AccessControlAction` set on their child — that prop must reach the wrapped element, not this component.
     */
    disableShortcut?: boolean
}

export const Shortcut = forwardRef<HTMLElement, ShortcutProps>(function Shortcut(
    { children, name, keybind, intent, interaction, scope = 'global', disableShortcut = false, priority = 0, ...rest },
    forwardedRef
): ReactElement {
    const { callbackRef } = useShortcut({
        name,
        keybind,
        intent,
        interaction,
        scope,
        disabled: disableShortcut,
        priority,
    })

    const mergedRef = useMergeRefs([callbackRef, forwardedRef])

    if (!isValidElement(children)) {
        throw new Error('Shortcut requires a single React element child')
    }

    const childProps = children.props as Record<string, unknown>
    const keybindStrings = keybind.map((kb) => kb.join('+')).join(',')

    // Append keyboard shortcut to tooltip if child has one
    let finalTooltip = childProps.tooltip
    if (childProps.tooltip && !disableShortcut) {
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

    // Forward props a parent injects onto this element (e.g. a wrapping LemonDropdown's onClick and
    // aria-haspopup) down to the real child, so Shortcut can sit between a dropdown and its trigger button.
    return cloneElement(children, {
        ...rest,
        ref: mergedRef,
        'data-shortcut-name': name,
        'data-shortcut-keybind': keybindStrings,
        'data-shortcut-intent': intent,
        'aria-keyshortcuts': keybindStrings,
        tooltip: finalTooltip,
        className: cn(childProps.className as string | undefined),
    } as Record<string, unknown>)
})
