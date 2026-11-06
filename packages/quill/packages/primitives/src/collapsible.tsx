import './collapsible.css'

import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { ChevronDownIcon, ChevronRightIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'

type CollapsibleVariant = 'default' | 'folder'

const CollapsibleVariantContext = React.createContext<CollapsibleVariant>('default')

type CollapsibleProps = CollapsiblePrimitive.Root.Props & {
    variant?: CollapsibleVariant
}

const Collapsible = React.forwardRef<React.ComponentRef<typeof CollapsiblePrimitive.Root>, CollapsibleProps>(
    function Collapsible({ variant = 'default', className, ...props }, ref) {
        return (
            <CollapsibleVariantContext.Provider value={variant}>
                <CollapsiblePrimitive.Root
                    ref={ref}
                    data-quill
                    data-slot="collapsible"
                    data-variant={variant}
                    className={cn(
                        'group/collapsible',
                        variant === 'default' && 'quill-collapsible--variant-default',
                        className
                    )}
                    {...props}
                />
            </CollapsibleVariantContext.Provider>
        )
    }
)

/**
 * Row container for the icon-only trigger pattern: the trigger toggles, while
 * siblings (a link, trailing count, actions) stay independently interactive.
 * Use `ms-auto` on trailing content so it stays end-aligned in RTL.
 */
const CollapsibleHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function CollapsibleHeader(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="collapsible-header"
            className={cn('quill-collapsible__header flex w-full items-center gap-1.5', className)}
            {...props}
        />
    )
})

const CollapsibleTrigger = React.forwardRef<
    React.ComponentRef<typeof CollapsiblePrimitive.Trigger>,
    CollapsiblePrimitive.Trigger.Props & {
        /**
         * Renders the trigger as a compact icon button (just the chevron) instead
         * of a full-width row — pair with `CollapsibleHeader` so the rest of the
         * row can hold independently clickable content. `children` become the
         * trigger's screen-reader-only label.
         */
        iconOnly?: boolean
        /**
         * Optional rest icon for `iconOnly` mode: shown instead of the chevron
         * until the surrounding `CollapsibleHeader` row is hovered or the trigger
         * is focused, then swaps to the chevron (Finder/VS Code tree pattern).
         */
        icon?: React.ReactNode
    }
>(function CollapsibleTrigger({ children, className, iconOnly = false, icon, ...props }, ref) {
    const variant = React.useContext(CollapsibleVariantContext)
    if (iconOnly) {
        return (
            <CollapsiblePrimitive.Trigger
                ref={ref}
                data-slot="collapsible-trigger"
                data-variant={variant}
                className={cn(
                    'quill-collapsible__trigger quill-collapsible__trigger--icon group/collapsible-trigger',
                    icon != null && 'quill-collapsible__trigger--swap',
                    className
                )}
                render={<Button size="icon-sm" />}
                {...props}
            >
                {/* Rest-icon display is owned by collapsible.css (hover/focus
                    swap) — a Tailwind display utility here would win the layer
                    war and break the hide-on-hover. */}
                {icon != null && (
                    <span data-slot="collapsible-trigger-rest-icon" className="pointer-events-none shrink-0">
                        {icon}
                    </span>
                )}
                {/* Single chevron rotated via CSS: points into reading direction
                    when closed (mirrored in RTL), down when open. */}
                <ChevronRightIcon
                    data-slot="collapsible-trigger-icon"
                    data-chevron="right"
                    className="pointer-events-none shrink-0"
                />
                {children != null && <span className="sr-only">{children}</span>}
            </CollapsiblePrimitive.Trigger>
        )
    }
    const chevrons = (
        <>
            <ChevronDownIcon
                data-slot="collapsible-trigger-icon"
                data-chevron="down"
                className="pointer-events-none shrink-0"
            />
            <ChevronUpIcon
                data-slot="collapsible-trigger-icon"
                data-chevron="up"
                className="pointer-events-none shrink-0"
            />
        </>
    )
    return (
        <CollapsiblePrimitive.Trigger
            ref={ref}
            data-slot="collapsible-trigger"
            data-variant={variant}
            className={cn(
                'quill-collapsible__trigger group/collapsible-trigger flex items-center gap-2 justify-start',
                variant === 'folder' && 'quill-collapsible__trigger--variant-folder',
                className
            )}
            render={<Button size="sm" />}
            {...props}
        >
            {variant === 'folder' && chevrons}
            {children}
            {variant === 'default' && chevrons}
        </CollapsiblePrimitive.Trigger>
    )
})

const CollapsibleContent = React.forwardRef<
    React.ComponentRef<typeof CollapsiblePrimitive.Panel>,
    CollapsiblePrimitive.Panel.Props
>(function CollapsibleContent({ children, className, ...props }, ref) {
    const variant = React.useContext(CollapsibleVariantContext)

    return (
        <CollapsiblePrimitive.Panel
            ref={ref}
            data-slot="collapsible-content"
            className="quill-collapsible__panel"
            {...props}
        >
            <div
                className={cn(
                    'quill-collapsible__panel-content',
                    variant === 'folder' && 'quill-collapsible__panel-content--variant-folder',
                    className
                )}
            >
                {children}
            </div>
        </CollapsiblePrimitive.Panel>
    )
})

export { Collapsible, CollapsibleHeader, CollapsibleTrigger, CollapsibleContent }
