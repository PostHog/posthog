import { Combobox as ComboboxPrimitive } from '@base-ui/react'
import { ChevronDownIcon, XIcon, CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Chip, ChipClose } from './chip'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from './input-group'
import { cn } from './lib/utils'
import { MenuLabel } from './menuLabel'
import { Separator } from './separator'

const ComboboxAnchorContext = React.createContext<React.RefObject<HTMLDivElement> | null>(null)

function Combobox<Value, Multiple extends boolean | undefined = false>({
    children,
    highlightItemOnHover = false,
    ...props
}: ComboboxPrimitive.Root.Props<Value, Multiple>): React.ReactElement {
    const anchorRef = React.useRef<HTMLDivElement>(null!)
    return (
        <ComboboxAnchorContext.Provider value={anchorRef}>
            <ComboboxPrimitive.Root
                highlightItemOnHover={highlightItemOnHover}
                {...props}
            >
                {children}
            </ComboboxPrimitive.Root>
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
                className={cn("[&_svg:not([class*='size-'])]:size-3.5", className)}
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
        <InputGroup ref={anchorRef} className={cn('w-auto', className)}>
            <ComboboxPrimitive.Input render={<InputGroupInput disabled={disabled} />} {...props} />
            <InputGroupAddon align="inline-end">
                {showTrigger && (
                    <InputGroupButton
                        size="icon-xs"
                        render={<ComboboxTrigger />}
                        data-slot="input-group-button"
                        className="group-has-data-[slot=combobox-clear]/input-group:hidden data-pressed:bg-transparent"
                        disabled={disabled}
                    />
                )}
                {showClear && <ComboboxClear disabled={disabled} />}
            </InputGroupAddon>
            {children}
        </InputGroup>
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
                side={side}
                sideOffset={sideOffset}
                align={align}
                alignOffset={alignOffset}
                anchor={anchor}
                className="isolate z-50"
            >
                <ComboboxPrimitive.Popup
                    data-slot="combobox-content"
                    data-chips={!!anchor}
                    className={cn(
                        'group/combobox-content relative flex flex-col max-h-(--available-height) min-w-[max(12rem,var(--anchor-width))] max-w-[min(24rem,var(--available-width))] origin-(--transform-origin) overflow-hidden rounded-lg bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-[side=bottom]:slide-in-from-top-2 data-[side=inline-end]:slide-in-from-start-2 data-[side=inline-start]:slide-in-from-end-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 *:data-[slot=input-group]:m-1 *:data-[slot=input-group]:mb-0 *:data-[slot=input-group]:h-7 *:data-[slot=input-group]:border-none *:data-[slot=input-group]:bg-input/20 *:data-[slot=input-group]:shadow-none dark:bg-popover data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95',
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
            className={cn(
                'min-h-0 max-h-[min(calc(--spacing(72)---spacing(9)),calc(var(--available-height)---spacing(9)))] scroll-py-1 has-data-[slot=combobox-list-footer]:scroll-pb-10 overflow-y-auto overscroll-contain p-1 has-data-[slot=combobox-list-footer]:pb-0 data-empty:p-0',
                className
            )}
            {...props}
        />
    )
}

function ComboboxItem({ className, children, title, ...props }: ComboboxPrimitive.Item.Props & { title?: string }): React.ReactElement {
    return (
        <ComboboxPrimitive.Item
            data-slot="combobox-item"
            className={cn(
                'w-full font-normal not-data-[variant=destructive]:data-highlighted:**:text-foreground data-disabled:pointer-events-none data-disabled:opacity-50 [&>.item]:border-0',
                'not-has-[>[data-slot=item]]:[&>button]:overflow-hidden',
                className
            )}
            render={<Button left className="relative aria-selected:pe-7" />}
            {...props}
        >
            <span className="inline-flex items-center gap-1.5 truncate" title={title ?? (typeof children === 'string' ? children : undefined)}>{children}</span>
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
    return (
        <ComboboxPrimitive.GroupLabel
            data-slot="combobox-label"
            className={className}
            render={<MenuLabel />}
            {...props}
        />
    )
}

function ComboboxCollection({ ...props }: ComboboxPrimitive.Collection.Props): React.ReactElement {
    return <ComboboxPrimitive.Collection data-slot="combobox-collection" {...props} />
}

function ComboboxEmpty({ className, ...props }: ComboboxPrimitive.Empty.Props): React.ReactElement {
    return (
        <ComboboxPrimitive.Empty
            data-slot="combobox-empty"
            className={cn(
                'hidden w-full justify-center py-2 text-center text-xs/relaxed text-muted-foreground group-data-empty/combobox-content:flex',
                className
            )}
            {...props}
        />
    )
}

function ComboboxSeparator({ className, ...props }: ComboboxPrimitive.Separator.Props): React.ReactElement {
    return (
        <ComboboxPrimitive.Separator
            data-slot="combobox-separator"
            className={cn('-mx-1 my-1 h-px bg-border/50', className)}
            {...props}
        />
    )
}

function ComboboxChips({
    className,
    ...props
}: React.ComponentPropsWithRef<typeof ComboboxPrimitive.Chips> & ComboboxPrimitive.Chips.Props): React.ReactElement {
    return (
        <ComboboxPrimitive.Chips
            data-slot="combobox-chips"
            className={cn(
                'flex min-h-8 flex-wrap items-center gap-1 rounded-md border border-input bg-input/20 bg-clip-padding px-2 py-1 text-xs/relaxed transition-colors focus-within:border-ring/50 focus-within:ring-2 focus-within:ring-ring/30 has-aria-invalid:border-destructive has-aria-invalid:ring-2 has-aria-invalid:ring-destructive/20 has-data-[slot=combobox-chip]:px-[0.175rem] dark:bg-input/30 dark:has-aria-invalid:border-destructive/50 dark:has-aria-invalid:ring-destructive/40',
                className
            )}
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
            render={<Chip className="pe-0" title={title ?? (typeof children === 'string' ? children : undefined)} />}
            data-slot="combobox-chip"
            className={cn(className)}
            {...props}
        >
            <span className="truncate flex-1">{children}</span>
            {showRemove && (
                <ComboboxPrimitive.ChipRemove render={<ChipClose />} data-slot="combobox-chip-remove">
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
            className={cn('min-w-16 flex-1 outline-none', className)}
            {...props}
        />
    )
}

function ComboboxListFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div data-slot="combobox-list-footer" className={cn("sticky -bottom-px bg-popover mt-1 -top-px", className)}>
            <Separator orientation="horizontal" className="-mx-2" />
            <div className="py-1" {...props} />
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
