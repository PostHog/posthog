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

// Helper function to convert platform-specific keybinds
function convertPlatformKeybinds(keybinds: string[][]): string[][] {
    return keybinds.map((keybind) => keybind.map((key) => (!IS_MAC && key === 'command' ? 'ctrl' : key)))
}

interface AppShortcutProps extends React.HTMLAttributes<HTMLElement>, Omit<AppShortcutType, 'ref' | 'keybind'> {
    /* The keybind(s) to use for the shortcut - can be a single keybind or multiple alternative keybinds */
    keybind: string[][]
    children: ReactNode
    /** Pass through props to the child element IMPORTANT, the child element must properly forward the ref what you're trying to interact with */
    asChild?: boolean
    /** The class name to apply to the element */
    className?: string
    /** If true, the keyboard shortcut will not be registered and tooltip keyboard shortcut will not be added to the childs tooltip */
    disabled?: boolean
    /** Custom ref for the focusable element (useful when child component doesn't forward ref to the focusable element) */
    targetRef?: React.RefObject<HTMLElement>
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
            targetRef,
            ...props
        },
        forwardedRef
    ): JSX.Element => {
        const internalRef = useRef<HTMLElement>(null)
        const [isRefReady, setIsRefReady] = useState(false)
        const { registerAppShortcut, unregisterAppShortcut } = useActions(appShortcutLogic)

        // keybind is already string[][], no normalization needed

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
                // Convert platform-specific keybinds
                const platformAgnosticKeybinds = convertPlatformKeybinds(keybind)

                // Use targetRef only when asChild is false (wrapper mode)
                // When asChild is true, always use internalRef (cloned child)
                const refToUse = !asChild && targetRef ? targetRef : internalRef
                registerAppShortcut({
                    name,
                    keybind: platformAgnosticKeybinds,
                    ref: refToUse,
                    intent,
                    interaction,
                    scope,
                })
            }
        }, [isRefReady, name, keybind, intent, interaction, scope, disabled, targetRef, asChild, registerAppShortcut])

        // Clean up on unmount
        useEffect(() => {
            return () => {
                unregisterAppShortcut(name)
            }
        }, [name, unregisterAppShortcut])

        const keybindStrings = keybind.map((kb) => kb.join('+')).join(',')

        const elementProps = {
            'data-shortcut-name': name,
            'data-shortcut-keybind': keybindStrings,
            'data-shortcut-intent': intent,
            'aria-keyshortcuts': keybindStrings,
            ref: handleRef,
            className: cn(className),
            ...props,
        }

        if (asChild && isValidElement(children)) {
            const childProps = children.props as any
            let finalTooltip = undefined

            // If the child has a tooltip prop and not disabled, append the keyboard shortcut(s) to it
            if (childProps.tooltip && !disabled) {
                finalTooltip = (
                    <>
                        {childProps.tooltip}{' '}
                        {keybind.map((kb, index) => (
                            <span key={index}>
                                {index > 0 && <span className="text-xs opacity-75"> or </span>}
                                <KeyboardShortcut
                                    {...keybindToKeyboardShortcutProps(kb)}
                                    className="relative text-xs -top-px"
                                />
                            </span>
                        ))}
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
