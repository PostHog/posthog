import { type ReactElement, type ReactNode, createContext, useCallback, useContext, useMemo, useState } from 'react'

import { cn } from '../utils'

// -- Context --

interface AccordionContextValue {
    expandedItems: Set<string>
    toggle: (value: string) => void
    multiple: boolean
}

const AccordionContext = createContext<AccordionContextValue | null>(null)

function useAccordionContext(): AccordionContextValue {
    const ctx = useContext(AccordionContext)
    if (!ctx) {
        throw new Error('Accordion compound components must be used within <Accordion>')
    }
    return ctx
}

// -- Accordion (root) --

export interface AccordionProps {
    children: ReactNode
    /** Allow multiple items open simultaneously */
    multiple?: boolean
    /** Initially expanded item values */
    defaultExpanded?: string[]
    className?: string
}

export function Accordion({
    children,
    multiple = false,
    defaultExpanded = [],
    className,
}: AccordionProps): ReactElement {
    const [expandedItems, setExpandedItems] = useState<Set<string>>(() => new Set(defaultExpanded))

    const toggle = useCallback(
        (value: string) => {
            setExpandedItems((prev) => {
                const next = new Set(prev)
                if (next.has(value)) {
                    next.delete(value)
                } else {
                    if (!multiple) {
                        next.clear()
                    }
                    next.add(value)
                }
                return next
            })
        },
        [multiple]
    )

    const ctx = useMemo(() => ({ expandedItems, toggle, multiple }), [expandedItems, toggle, multiple])

    return (
        <AccordionContext.Provider value={ctx}>
            <div className={cn('divide-y divide-border-primary', className)}>{children}</div>
        </AccordionContext.Provider>
    )
}

// -- AccordionItem --

interface AccordionItemContextValue {
    value: string
    isExpanded: boolean
}

const AccordionItemContext = createContext<AccordionItemContextValue | null>(null)

function useAccordionItemContext(): AccordionItemContextValue {
    const ctx = useContext(AccordionItemContext)
    if (!ctx) {
        throw new Error('AccordionTrigger/AccordionContent must be used within <AccordionItem>')
    }
    return ctx
}

export interface AccordionItemProps {
    value: string
    children: ReactNode
    className?: string
}

export function AccordionItem({ value, children, className }: AccordionItemProps): ReactElement {
    const { expandedItems } = useAccordionContext()
    const isExpanded = expandedItems.has(value)
    const itemCtx = useMemo(() => ({ value, isExpanded }), [value, isExpanded])

    return (
        <AccordionItemContext.Provider value={itemCtx}>
            <div className={className}>{children}</div>
        </AccordionItemContext.Provider>
    )
}

// -- AccordionTrigger --

export interface AccordionTriggerProps {
    children: ReactNode
    className?: string
}

export function AccordionTrigger({ children, className }: AccordionTriggerProps): ReactElement {
    const { toggle } = useAccordionContext()
    const { value, isExpanded } = useAccordionItemContext()

    return (
        <button
            type="button"
            aria-expanded={isExpanded}
            onClick={() => toggle(value)}
            className={cn(
                'flex w-full items-center gap-2 py-2 text-left text-sm cursor-pointer transition-colors',
                'hover:bg-bg-tertiary',
                className
            )}
        >
            <span
                className={cn(
                    'text-[10px] text-text-secondary transition-transform shrink-0',
                    isExpanded ? 'rotate-90' : 'rotate-0'
                )}
            >
                &#9654;
            </span>
            <span className="flex-1 min-w-0">{children}</span>
        </button>
    )
}

// -- AccordionContent --

export interface AccordionContentProps {
    children: ReactNode
    className?: string
}

export function AccordionContent({ children, className }: AccordionContentProps): ReactElement | null {
    const { isExpanded } = useAccordionItemContext()

    if (!isExpanded) {
        return null
    }

    return <div className={cn('pb-2', className)}>{children}</div>
}
