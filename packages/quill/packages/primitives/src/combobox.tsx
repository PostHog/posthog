import './combobox.css'

import { Combobox as ComboboxPrimitive } from '@base-ui/react'
import { ChevronDownIcon, XIcon, CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Chip, ChipClose } from './chip'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from './input-group'
import { cn } from './lib/utils'
import { MenuEmpty } from './menu-empty'
import { MenuItemBody } from './menu-item-body'
import { MenuLabel } from './menu-label'
import { hasTooltipContent, withTooltip } from './with-tooltip'

const ComboboxAnchorContext = React.createContext<React.RefObject<HTMLDivElement> | null>(null)

function Combobox<Value, Multiple extends boolean | undefined = false>({
    children,
    ...props
}: ComboboxPrimitive.Root.Props<Value, Multiple>): React.ReactElement {
    const anchorRef = React.useRef<HTMLDivElement>(null!)
    return (
        <ComboboxAnchorContext.Provider value={anchorRef}>
            <ComboboxPrimitive.Root {...props}>{children}</ComboboxPrimitive.Root>
        </ComboboxAnchorContext.Provider>
    )
}

function ComboboxValue({ ...props }: ComboboxPrimitive.Value.Props): React.ReactElement {
    return <ComboboxPrimitive.Value data-slot="combobox-value" {...props} />
}

const ComboboxTrigger = React.forwardRef<HTMLButtonElement, ComboboxPrimitive.Trigger.Props>(
    ({ className, children, ...props }, ref) => {
        return (
            <ComboboxPrimitive.Trigger
                ref={ref}
                data-slot="combobox-trigger"
                className={cn('quill-combobox__trigger', className)}
                {...props}
            >
                {children}
                <ChevronDownIcon className="pointer-events-none size-3.5 text-muted-foreground" />
            </ComboboxPrimitive.Trigger>
        )
    }
)
ComboboxTrigger.displayName = 'ComboboxTrigger'

const ComboboxClear = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Clear>,
    ComboboxPrimitive.Clear.Props
>(function ComboboxClear({ className, ...props }, ref) {
    return (
        <ComboboxPrimitive.Clear
            ref={ref}
            data-slot="combobox-clear"
            render={<InputGroupButton size="icon-xs" />}
            className={cn(className)}
            {...props}
        >
            <XIcon className="pointer-events-none" />
        </ComboboxPrimitive.Clear>
    )
})

const ComboboxInput = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Input>,
    ComboboxPrimitive.Input.Props & {
        showTrigger?: boolean
        showClear?: boolean
    }
>(function ComboboxInput(
    { className, children, disabled = false, showTrigger = true, showClear = false, ...props },
    ref
) {
    const anchorRef = React.useContext(ComboboxAnchorContext)
    return (
        <div data-slot="combobox-input-group-wrapper">
            <InputGroup ref={anchorRef} className={cn('w-auto', className)}>
                <ComboboxPrimitive.Input ref={ref} render={<InputGroupInput disabled={disabled} />} {...props} />
                <InputGroupAddon align="inline-end">
                    {showTrigger && (
                        <InputGroupButton
                            size="icon-xs"
                            render={<ComboboxTrigger />}
                            data-slot="input-group-button"
                            className="group-has-data-[slot=combobox-clear]/input-group:hidden data-pressed:bg-transparent rounded-xs"
                            disabled={disabled}
                        />
                    )}
                    {showClear && <ComboboxClear disabled={disabled} />}
                </InputGroupAddon>
                {children}
            </InputGroup>
        </div>
    )
})

const ComboboxContent = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Popup>,
    ComboboxPrimitive.Popup.Props & {
        /**
         * Rendered in the positioner as the popup's sibling, escaping the popup's overflow. Use position: absolute —
         * in-flow content here resizes the box the positioner measures.
         */
        popupSibling?: React.ReactNode
    } & Pick<ComboboxPrimitive.Positioner.Props, 'side' | 'align' | 'sideOffset' | 'alignOffset' | 'anchor'>
>(function ComboboxContent(
    {
        className,
        popupSibling,
        side = 'bottom',
        sideOffset = 6,
        align = 'start',
        alignOffset = 0,
        anchor: anchorProp,
        ...props
    },
    ref
) {
    const contextAnchor = React.useContext(ComboboxAnchorContext)
    const anchor = anchorProp ?? contextAnchor
    return (
        <ComboboxPrimitive.Portal>
            <ComboboxPrimitive.Positioner
                data-quill
                data-quill-portal="popover"
                side={side}
                sideOffset={sideOffset}
                align={align}
                alignOffset={alignOffset}
                anchor={anchor}
                className="isolate"
            >
                {popupSibling}
                <ComboboxPrimitive.Popup
                    ref={ref}
                    data-slot="combobox-content"
                    data-chips={!!anchor}
                    className={cn('quill-combobox__content group/combobox-content', className)}
                    {...props}
                />
            </ComboboxPrimitive.Positioner>
        </ComboboxPrimitive.Portal>
    )
})

const ComboboxList = React.forwardRef<React.ComponentRef<typeof ComboboxPrimitive.List>, ComboboxPrimitive.List.Props>(
    function ComboboxList({ className, ...props }, ref) {
        return (
            <ComboboxPrimitive.List
                ref={ref}
                data-slot="combobox-list"
                // `scroll-mask-t-4` always (top fade for items scrolling out of view).
                // Bottom fade is conditional: if a `ComboboxListFooter` is rendered,
                // the footer's own `quill-scroll-fade-top` pseudo handles the bottom
                // fade (and only when content is actually hidden below, via
                // container scroll-state). Otherwise, fall back to plugin's
                // `scroll-mask-b-4` for the same behavior on lists without a footer.
                className={cn(
                    'quill-combobox__list scroll-mask-t-4 scroll-py-4',
                    'not-has-[[data-slot=combobox-list-footer]]:scroll-mask-b-4',
                    className
                )}
                {...props}
            />
        )
    }
)

const ComboboxItem = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Item>,
    ComboboxPrimitive.Item.Props & {
        title?: string
        /** Text shown in a tooltip beside the item. */
        tooltip?: React.ReactNode
        /** Disables the item and says why in a tooltip beside it. Takes the place of `tooltip` while set. */
        disabledReason?: React.ReactNode
        /** An action row, such as "New project". It is never selected, so it leaves out the check mark's gutter. */
        action?: boolean
        /** A muted second line under the label. The row grows to fit it, and its text lines up past a leading icon. */
        description?: React.ReactNode
    }
>(function ComboboxItem(
    { className, children, title, tooltip, disabledReason, disabled, action, description, ...props },
    ref
) {
    const hasReason = hasTooltipContent(disabledReason)
    const described = hasTooltipContent(description)
    // A disabled item ignores the pointer, so the tooltip listens on a wrapper and opens beside the row.
    return withTooltip(
        <ComboboxPrimitive.Item
            ref={ref}
            data-slot="combobox-item"
            data-action={action ? '' : undefined}
            disabled={disabled || hasReason}
            className={cn('quill-combobox__item', described && 'quill-menu-item--described', className)}
            title={title ?? (typeof children === 'string' ? children : undefined)}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button size="row" left className="min-w-0 aria-selected:bg-fill-selected" />}
            {...props}
        >
            <span className="quill-combobox__item-content flex items-center min-w-0 truncate">
                {described ? <MenuItemBody description={description}>{children}</MenuItemBody> : children}
            </span>
            <ComboboxPrimitive.ItemIndicator
                render={<span className="pointer-events-none absolute start-2 flex items-center justify-center" />}
            >
                <CheckIcon className="quill-combobox__indicator-icon pointer-events-none size-3.5" />
            </ComboboxPrimitive.ItemIndicator>
        </ComboboxPrimitive.Item>,
        hasReason ? disabledReason : tooltip,
        { target: 'block', side: 'inline-end' }
    )
})

const ComboboxGroup = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Group>,
    ComboboxPrimitive.Group.Props
>(function ComboboxGroup({ className, ...props }, ref) {
    return <ComboboxPrimitive.Group ref={ref} data-slot="combobox-group" className={cn(className)} {...props} />
})

const ComboboxLabel = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.GroupLabel>,
    ComboboxPrimitive.GroupLabel.Props
>(function ComboboxLabel({ className, ...props }, ref) {
    return (
        <ComboboxPrimitive.GroupLabel
            ref={ref}
            data-slot="combobox-label"
            className={className}
            render={<MenuLabel />}
            {...props}
        />
    )
})

function ComboboxCollection({ ...props }: ComboboxPrimitive.Collection.Props): React.ReactElement {
    return <ComboboxPrimitive.Collection data-slot="combobox-collection" {...props} />
}

const ComboboxEmpty = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Empty>,
    ComboboxPrimitive.Empty.Props
>(function ComboboxEmpty({ className, ...props }, ref) {
    // Base UI renders the children only when nothing matches, so `empty:hidden` is the whole visibility rule.
    return (
        <ComboboxPrimitive.Empty
            ref={ref}
            data-slot="combobox-empty"
            className={cn('empty:hidden', className)}
            render={<MenuEmpty />}
            {...props}
        />
    )
})

const ComboboxSeparator = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Separator>,
    ComboboxPrimitive.Separator.Props
>(function ComboboxSeparator({ className, ...props }, ref) {
    return (
        <ComboboxPrimitive.Separator
            ref={ref}
            data-slot="combobox-separator"
            className={cn('quill-combobox__separator', className)}
            {...props}
        />
    )
})

const ComboboxChips = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Chips>,
    React.ComponentPropsWithRef<typeof ComboboxPrimitive.Chips> & ComboboxPrimitive.Chips.Props
>(function ComboboxChips({ className, ...props }, ref) {
    return (
        <ComboboxPrimitive.Chips
            ref={ref}
            data-slot="combobox-chips"
            className={cn('quill-combobox__chips flex flex-wrap items-center gap-1 py-1', className)}
            {...props}
        />
    )
})

const ComboboxChip = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Chip>,
    ComboboxPrimitive.Chip.Props & {
        showRemove?: boolean
        title?: string
    }
>(function ComboboxChip({ className, children, title, showRemove = true, ...props }, ref) {
    return (
        <ComboboxPrimitive.Chip
            ref={ref}
            render={<Chip title={title ?? (typeof children === 'string' ? children : undefined)} />}
            data-slot="combobox-chip"
            className={cn(className)}
            {...props}
        >
            <span className="truncate flex-1">{children}</span>
            {showRemove && (
                <ComboboxPrimitive.ChipRemove render={<ChipClose />}>
                    <XIcon className="pointer-events-none" />
                </ComboboxPrimitive.ChipRemove>
            )}
        </ComboboxPrimitive.Chip>
    )
})

const ComboboxChipsInput = React.forwardRef<
    React.ComponentRef<typeof ComboboxPrimitive.Input>,
    ComboboxPrimitive.Input.Props
>(function ComboboxChipsInput({ className, ...props }, ref) {
    return (
        <ComboboxPrimitive.Input
            ref={ref}
            data-slot="combobox-chip-input"
            className={cn('quill-combobox__chips-input', className)}
            {...props}
        />
    )
})

const ComboboxListFooter = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ComboboxListFooter(
    { className, ...props },
    ref
) {
    return (
        <div
            data-slot="combobox-list-footer"
            // `quill-scroll-fade-top` adds a `var(--card) → transparent` gradient
            // pseudo-element above the footer, gated by container scroll-state on
            // the parent list. Renders only when items are hidden below the visible
            // area, mirroring `scroll-mask-b` without fading the footer itself.
            className={cn('quill-combobox__list-footer quill-scroll-fade-top', className)}
        >
            <div ref={ref} className="p-1" {...props} />
        </div>
    )
})

function useComboboxAnchor(): React.RefObject<HTMLDivElement> {
    const contextRef = React.useContext(ComboboxAnchorContext)
    if (contextRef === null) {
        throw new Error('useComboboxAnchor must be used within a Combobox')
    }
    return contextRef
}

export {
    Combobox,
    ComboboxInput,
    ComboboxContent,
    ComboboxList,
    ComboboxItem,
    ComboboxGroup,
    ComboboxLabel,
    ComboboxCollection,
    ComboboxEmpty,
    ComboboxListFooter,
    ComboboxSeparator,
    ComboboxChips,
    ComboboxChip,
    ComboboxChipsInput,
    ComboboxTrigger,
    ComboboxValue,
    useComboboxAnchor,
}
