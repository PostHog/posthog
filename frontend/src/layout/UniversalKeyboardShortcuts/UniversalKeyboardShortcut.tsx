import { useActions, useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import React, {
    cloneElement,
    forwardRef,
    isValidElement,
    ReactNode,
    useCallback,
    useEffect,
    useRef,
    useState,
} from 'react'

import { UniversalKeyboardShortcutItem, universalKeyboardShortcutsLogic } from './universalKeyboardShortcutsLogic'

interface UniversalShortcutProps extends React.HTMLAttributes<HTMLElement>, Omit<UniversalKeyboardShortcutItem, 'ref'> {
    children: ReactNode
    asChild?: boolean
    className?: string
}

export const UniversalKeyboardShortcut = forwardRef<HTMLElement, UniversalShortcutProps>(
    (
        { children, asChild = false, name, category, keybind, intent, interaction, className, ...props },
        forwardedRef
    ): JSX.Element => {
        const internalRef = useRef<HTMLElement>(null)
        const [isRefReady, setIsRefReady] = useState(false)
        const { registeredKeyboardShortcuts } = useValues(universalKeyboardShortcutsLogic)
        const { registerKeyboardShortcut, unregisterKeyboardShortcut } = useActions(universalKeyboardShortcutsLogic)

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
                const isAlreadyRegistered = registeredKeyboardShortcuts.some((shortcut) => shortcut.name === name)
                if (!isAlreadyRegistered) {
                    registerKeyboardShortcut({ name, category, keybind, ref: internalRef, intent, interaction })
                }
            }
        }, [isRefReady, name, category, keybind])

        // Clean up on unmount
        useEffect(() => {
            return () => {
                unregisterKeyboardShortcut(name)
            }
        }, [name])

        const elementProps = {
            'data-shortcut-name': name,
            'data-shortcut-category': category,
            'data-shortcut-keybind': keybind,
            'data-shortcut-intent': intent,
            'aria-keyshortcuts': keybind.replaceAll(' ', '+'),
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

UniversalKeyboardShortcut.displayName = 'UniversalKeyboardShortcut'
