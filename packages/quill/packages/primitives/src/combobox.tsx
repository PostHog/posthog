import { Combobox as ComboboxPrimitive } from '@base-ui/react'
import { ChevronDownIcon, XIcon, CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Chip, ChipClose } from './chip'
import './combobox.css'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from './input-group'
import { cn } from './lib/utils'
import { MenuEmpty } from './menu-empty'
import { MenuLabel } from './menu-label'

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

function ComboboxClear({ className, ...props }: ComboboxPrimitive.Clear.Props): React.ReactElement {
    return (
        <ComboboxPrimitive.Clear
            data-slot="combobox-clear"
            render={<InputGroupButton size="icon-xs" />}
            className={cn(className)}
            {...props}
        >
            <XIcon className="pointer-events-none" />
        </ComboboxPrimitive.Clear>
    )
}

function ComboboxInput({
    className,
    children,
    disabled = false,
    showTrigger = true,
    showClear = false,
    ...props
}: ComboboxPrimitive.Input.Props & {
    showTrigger?: boolean
    showClear?: boolean
}): React.ReactElement {
    const anchorRef = React.useContext(ComboboxAnchorContext)
    return (
        <div data-slot="combobox-input-group-wrapper">
            <InputGroup ref={anchorRef} className={cn('w-auto', className)}>
                <ComboboxPrimitive.Input render={<InputGroupInput disabled={disabled} />} {...props} />
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
}

function ComboboxContent({
    className,
    side = 'bottom',
    sideOffset = 6,
    align = 'start',
    alignOffset = 0,
    anchor: anchorProp,
    ...props
}: ComboboxPrimitive.Popup.Props &
    Pick<
        ComboboxPrimitive.Positioner.Props,
        'side' | 'align' | 'sideOffset' | 'alignOffset' | 'anchor'
    >): React.ReactElement {
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
                <ComboboxPrimitive.Popup
                    data-slot="combobox-content"
                    data-chips={!!anchor}
                    className={cn(
                        'quill-combobox__content group/combobox-content',
                        className
                    )}
                    {...props}
                />
            </ComboboxPrimitive.Positioner>
        </ComboboxPrimitive.Portal>
    )
}

function ComboboxList({ className, ...props }: ComboboxPrimitive.List.Props): React.ReactElement {
    return (
        <ComboboxPrimitive.List
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
                className,
            )}
            {...props}
        />
    )
}

function ComboboxItem({
    className,
    children,
    title,
    ...props
}: ComboboxPrimitive.Item.Props & { title?: string }): React.ReactElement {
    return (
        <ComboboxPrimitive.Item
            data-slot="combobox-item"
            className={cn('quill-combobox__item', className)}
            title={title ?? (typeof children === 'string' ? children : undefined)}
            render={
                <Button
                    left
                    className="min-w-0 aria-selected:pe-7 aria-selected:bg-fill-selected data-highlighted:border-ring data-highlighted:ring-2 data-highlighted:ring-ring/30 ring-offset-1"
                />
            }
            {...props}
        >
            <span className="flex items-center gap-1.5 min-w-0 truncate">{children}</span>
            <ComboboxPrimitive.ItemIndicator
                render={<span className="pointer-events-none absolute end-2 flex items-center justify-center" />}
            >
                <CheckIcon className="pointer-events-none" />
            </ComboboxPrimitive.ItemIndicator>
        </ComboboxPrimitive.Item>
    )
}

function ComboboxGroup({ className, ...props }: ComboboxPrimitive.Group.Props): React.ReactElement {
    return <ComboboxPrimitive.Group data-slot="combobox-group" className={cn(className)} {...props} />
}

function ComboboxLabel({ className, ...props }: ComboboxPrimitive.GroupLabel.Props): React.ReactElement {
    return <ComboboxPrimitive.GroupLabel data-slot="combobox-label" className={className} render={<MenuLabel />} {...props} />
}

function ComboboxCollection({ ...props }: ComboboxPrimitive.Collection.Props): React.ReactElement {
    return <ComboboxPrimitive.Collection data-slot="combobox-collection" {...props} />
}

function ComboboxEmpty({ className, children, ...props }: ComboboxPrimitive.Empty.Props): React.ReactElement {
    return (
        <ComboboxPrimitive.Empty
            data-slot="combobox-empty"
            className={cn('hidden group-data-empty/combobox-content:flex', className)}
            {...props}
            render={<MenuEmpty>{children}</MenuEmpty>}
        />
    )
}

function ComboboxSeparator({ className, ...props }: ComboboxPrimitive.Separator.Props): React.ReactElement {
    return <ComboboxPrimitive.Separator data-slot="combobox-separator" className={cn('quill-combobox__separator', className)} {...props} />
}

function ComboboxChips({
    className,
    ...props
}: React.ComponentPropsWithRef<typeof ComboboxPrimitive.Chips> & ComboboxPrimitive.Chips.Props): React.ReactElement {
    return (
        <ComboboxPrimitive.Chips
            data-slot="combobox-chips"
            className={cn('quill-combobox__chips flex flex-wrap items-center gap-1', className)}
            {...props}
        />
    )
}

function ComboboxChip({
    className,
    children,
    title,
    showRemove = true,
    ...props
}: ComboboxPrimitive.Chip.Props & {
    showRemove?: boolean
    title?: string
}): React.ReactElement {
    return (
        <ComboboxPrimitive.Chip
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
}

function ComboboxChipsInput({ className, ...props }: ComboboxPrimitive.Input.Props): React.ReactElement {
    return (
        <ComboboxPrimitive.Input
            data-slot="combobox-chip-input"
            className={cn('quill-combobox__chips-input', className)}
            {...props}
        />
    )
}

function ComboboxListFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="combobox-list-footer"
            // `quill-scroll-fade-top` adds a `var(--card) → transparent` gradient
            // pseudo-element above the footer, gated by container scroll-state on
            // the parent list. Renders only when items are hidden below the visible
            // area, mirroring `scroll-mask-b` without fading the footer itself.
            className={cn('quill-combobox__list-footer quill-scroll-fade-top', className)}
        >
            <div className="p-1" {...props} />
        </div>
    )
}

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
