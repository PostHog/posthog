import { useActions } from 'kea'
import React, {
    ReactNode,
    cloneElement,
    forwardRef,
    isValidElement,
    useCallback,
    useEffect,
    useRef,
    useState,
} from 'react'

import { isMac } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { AppShortcutType, appShortcutLogic } from './appShortcutLogic'

const IS_MAC = isMac()

// Helper function to convert keybind array to KeyboardShortcut props
function keybindToKeyboardShortcutProps(keybind: string[]): Record<string, boolean> {
    const platformAgnosticKeybind = keybind.map((key) => (!IS_MAC && key === 'command' ? 'ctrl' : key))
    return Object.fromEntries(platformAgnosticKeybind.map((key) => [key, true]))
}

interface AppShortcutProps extends React.HTMLAttributes<HTMLElement>, Omit<AppShortcutType, 'ref'> {
    children: ReactNode
    asChild?: boolean
    className?: string
    disabled?: boolean
}

export const AppShortcut = forwardRef<HTMLElement, AppShortcutProps>(
    (
        {
            children,
            asChild = false,
            name,
            keybind,
            intent,
            interaction,
            scope = 'global',
            className,
            disabled = false,
            ...props
        },
        forwardedRef
    ): JSX.Element => {
        const internalRef = useRef<HTMLElement>(null)
        const [isRefReady, setIsRefReady] = useState(false)
        const { registerAppShortcut, unregisterAppShortcut } = useActions(appShortcutLogic)

        // Use callback ref to track when element is ready
        const handleRef = useCallback(
            (node: HTMLElement | null) => {
                // Handle internal ref
                ;(internalRef as React.MutableRefObject<HTMLElement | null>).current = node
                setIsRefReady(!!node)

                // Handle forwarded ref
                if (typeof forwardedRef === 'function') {
                    forwardedRef(node)
                } else if (forwardedRef) {
                    forwardedRef.current = node
                }
            },
            [forwardedRef]
        )

        // Register shortcut when ref is ready
        useEffect(() => {
            if (isRefReady && internalRef.current && !disabled) {
                // Replace 'command' with 'ctrl' when not on Mac
                const platformAgnosticKeybind = keybind.map((key) => (!IS_MAC && key === 'command' ? 'ctrl' : key))
                registerAppShortcut({
                    name,
                    keybind: platformAgnosticKeybind,
                    ref: internalRef,
                    intent,
                    interaction,
                    scope,
                })
            }
        }, [isRefReady, name, keybind, intent, interaction, scope, disabled, registerAppShortcut])

        // Clean up on unmount
        useEffect(() => {
            return () => {
                unregisterAppShortcut(name)
            }
        }, [name, unregisterAppShortcut])

        const elementProps = {
            'data-shortcut-name': name,
            'data-shortcut-keybind': keybind.join('+'),
            'data-shortcut-intent': intent,
            'aria-keyshortcuts': keybind.join('+'),
            ref: handleRef,
            className: cn(className),
            ...props,
        }

        if (asChild && isValidElement(children)) {
            const childProps = children.props as any
            let finalTooltip = undefined

            // If the child has a tooltip prop and not disabled, append the keyboard shortcut to it
            if (childProps.tooltip && !disabled) {
                finalTooltip = (
                    <>
                        {childProps.tooltip}{' '}
                        <KeyboardShortcut
                            {...keybindToKeyboardShortcutProps(keybind)}
                            className="relative text-xs -top-px"
                        />
                    </>
                )
            } else if (childProps.tooltip) {
                // If disabled, just use the original tooltip without keyboard shortcut
                finalTooltip = childProps.tooltip
            }

            return cloneElement(children as React.ReactElement, {
                ...children.props,
                ...elementProps,
                tooltip: finalTooltip,
                className: cn(children.props.className, className),
            })
        }

        return <div {...(elementProps as React.HTMLAttributes<HTMLDivElement>)}>{children}</div>
    }
)

AppShortcut.displayName = 'AppShortcut'
