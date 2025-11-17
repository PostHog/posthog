import { useActions, useValues } from 'kea'
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

import { appShortcutDeuxLogic } from './appShortcutDeuxLogic'
import { AppShortcutDeuxType } from './appShortcutDeuxLogic'

const IS_MAC = isMac()

interface AppShortcutDeuxProps extends React.HTMLAttributes<HTMLElement>, Omit<AppShortcutDeuxType, 'ref'> {
    children: ReactNode
    asChild?: boolean
    className?: string
}

export const AppShortcutDeux = forwardRef<HTMLElement, AppShortcutDeuxProps>(
    (
        { children, asChild = false, name, keybind, intent, interaction, className, ...props },
        forwardedRef
    ): JSX.Element => {
        const internalRef = useRef<HTMLElement>(null)
        const [isRefReady, setIsRefReady] = useState(false)
        const { registeredAppShortcuts } = useValues(appShortcutDeuxLogic)
        const { registerAppShortcut, unregisterAppShortcut } = useActions(appShortcutDeuxLogic)

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
            if (isRefReady && internalRef.current) {
                // Check if already registered to prevent duplicates
                const isAlreadyRegistered = registeredAppShortcuts.some((shortcut) => shortcut.name === name)
                if (!isAlreadyRegistered) {
                    // Replace 'command' with 'ctrl' when not on Mac
                    const platformAgnosticKeybind = keybind.map((key) => (!IS_MAC && key === 'command' ? 'ctrl' : key))
                    registerAppShortcut({
                        name,
                        keybind: platformAgnosticKeybind,
                        ref: internalRef,
                        intent,
                        interaction,
                    })
                }
            }
        }, [isRefReady, name, keybind, intent, interaction, registeredAppShortcuts, registerAppShortcut])

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
            return cloneElement(children as React.ReactElement, {
                ...children.props,
                ...elementProps,
                className: cn(children.props.className, className),
            })
        }

        return <div {...(elementProps as React.HTMLAttributes<HTMLDivElement>)}>{children}</div>
    }
)

AppShortcutDeux.displayName = 'AppShortcutDeux'
