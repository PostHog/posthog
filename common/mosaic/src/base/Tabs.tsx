import { type ReactElement, type ReactNode, createContext, useCallback, useContext, useMemo, useState } from 'react'

import { cn } from '../utils'

// -- Context --

interface TabsContextValue {
    value: string
    onValueChange: (value: string) => void
}

const TabsContext = createContext<TabsContextValue | null>(null)

function useTabsContext(): TabsContextValue {
    const ctx = useContext(TabsContext)
    if (!ctx) {
        throw new Error('Tabs compound components must be used within <Tabs>')
    }
    return ctx
}

// -- Tabs (root) --

export interface TabsProps {
    defaultValue: string
    value?: string
    onValueChange?: (value: string) => void
    children: ReactNode
    className?: string
}

export function Tabs({
    defaultValue,
    value: controlledValue,
    onValueChange,
    children,
    className,
}: TabsProps): ReactElement {
    const [uncontrolledValue, setUncontrolledValue] = useState(defaultValue)

    const isControlled = controlledValue !== undefined
    const activeValue = isControlled ? controlledValue : uncontrolledValue

    const handleChange = useCallback(
        (newValue: string) => {
            if (!isControlled) {
                setUncontrolledValue(newValue)
            }
            onValueChange?.(newValue)
        },
        [isControlled, onValueChange]
    )

    const ctx = useMemo(() => ({ value: activeValue, onValueChange: handleChange }), [activeValue, handleChange])

    return (
        <TabsContext.Provider value={ctx}>
            <div className={className}>{children}</div>
        </TabsContext.Provider>
    )
}

// -- TabsList --

export interface TabsListProps {
    children: ReactNode
    className?: string
}

export function TabsList({ children, className }: TabsListProps): ReactElement {
    return (
        <div
            role="tablist"
            className={cn('flex border-b border-border-primary gap-0 overflow-x-auto', className)}
            style={{ scrollbarWidth: 'none' }}
        >
            {children}
        </div>
    )
}

// -- TabsTrigger --

export interface TabsTriggerProps {
    value: string
    children: ReactNode
    className?: string
}

export function TabsTrigger({ value, children, className }: TabsTriggerProps): ReactElement {
    const { value: activeValue, onValueChange } = useTabsContext()
    const isActive = activeValue === value

    return (
        <button
            role="tab"
            aria-selected={isActive}
            onClick={() => onValueChange(value)}
            className={cn(
                'px-3 py-2 text-sm font-medium whitespace-nowrap cursor-pointer transition-colors',
                'border-b-2 -mb-px',
                'hover:text-text-primary',
                isActive ? 'border-info text-info' : 'border-transparent text-text-secondary',
                className
            )}
        >
            {children}
        </button>
    )
}

// -- TabsContent --

export interface TabsContentProps {
    value: string
    children: ReactNode
    className?: string
}

export function TabsContent({ value, children, className }: TabsContentProps): ReactElement | null {
    const { value: activeValue } = useTabsContext()

    if (activeValue !== value) {
        return null
    }

    return (
        <div role="tabpanel" className={cn('pt-3', className)}>
            {children}
        </div>
    )
}
