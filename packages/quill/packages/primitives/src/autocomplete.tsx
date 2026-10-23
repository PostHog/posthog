import { Autocomplete as AutocompletePrimitive } from '@base-ui/react/autocomplete'
import { ChevronDownIcon, SearchIcon, XIcon } from 'lucide-react'
import * as React from 'react'

import './autocomplete.css'
import { Button } from './button'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from './input-group'
import { cn } from './lib/utils'
import { MenuEmpty } from './menu-empty'
import { MenuLabel } from './menu-label'
import { Separator } from './separator'

const AutocompleteAnchorContext = React.createContext<React.RefObject<HTMLDivElement> | null>(null)

// AutocompletePrimitive.Root has two overloads (flat-items vs grouped-items) that
// TypeScript can't disambiguate when we spread props through our wrapper. The
// underlying runtime is the same; cast to a permissive component type so consumers
// of `<Autocomplete>` still see the full Props<Value> surface from the public
// signature on `Autocomplete` below.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const AutocompleteRoot = AutocompletePrimitive.Root as unknown as React.FC<any>

function Autocomplete<Value>({
    children,
    autoHighlight = true,
    ...props
}: AutocompletePrimitive.Root.Props<Value> & {
    items?: readonly Value[] | readonly { items: readonly Value[] }[]
}): React.ReactElement {
    const anchorRef = React.useRef<HTMLDivElement>(null!)
    return (
        <AutocompleteAnchorContext.Provider value={anchorRef}>
            <AutocompleteRoot {...props} autoHighlight={autoHighlight}>
                {children}
            </AutocompleteRoot>
        </AutocompleteAnchorContext.Provider>
    )
}

function AutocompleteValue({ ...props }: AutocompletePrimitive.Value.Props): React.ReactElement {
    return <AutocompletePrimitive.Value data-slot="autocomplete-value" {...props} />
}

const AutocompleteTrigger = React.forwardRef<HTMLButtonElement, AutocompletePrimitive.Trigger.Props>(
    ({ className, children, ...props }, ref) => (
        <AutocompletePrimitive.Trigger
            ref={ref}
            data-slot="autocomplete-trigger"
            className={cn('quill-autocomplete__trigger', className)}
            {...props}
        >
            {children}
            <ChevronDownIcon className="pointer-events-none size-3.5 text-muted-foreground" />
        </AutocompletePrimitive.Trigger>
    )
)
AutocompleteTrigger.displayName = 'AutocompleteTrigger'

const AutocompleteClear = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.Clear>,
    AutocompletePrimitive.Clear.Props
>(function AutocompleteClear({ className, ...props }, ref) {
    return (
        <AutocompletePrimitive.Clear
            ref={ref}
            data-slot="autocomplete-clear"
            render={<InputGroupButton size="icon-xs" />}
            className={cn(className)}
            {...props}
        >
            <XIcon className="pointer-events-none" />
        </AutocompletePrimitive.Clear>
    )
})

const AutocompleteInput = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.Input>,
    AutocompletePrimitive.Input.Props & {
        /** Render the leading search icon (default true). */
        showSearchIcon?: boolean
        /** Render the trailing clear button (default false). */
        showClear?: boolean
    }
>(function AutocompleteInput(
    { className, children, disabled = false, showSearchIcon = true, showClear = false, ...props },
    ref
) {
    const anchorRef = React.useContext(AutocompleteAnchorContext)
    return (
        <div data-slot="autocomplete-input-group-wrapper">
            <InputGroup ref={anchorRef} className={cn('w-auto', className)}>
                {showSearchIcon && (
                    <InputGroupAddon align="inline-start">
                        <SearchIcon />
                    </InputGroupAddon>
                )}
                <AutocompletePrimitive.Input ref={ref} render={<InputGroupInput disabled={disabled} />} {...props} />
                {children ? <InputGroupAddon align="inline-end">{children}</InputGroupAddon> : null}
                {showClear && (
                    <InputGroupAddon align="inline-end">
                        <AutocompleteClear disabled={disabled} />
                    </InputGroupAddon>
                )}
            </InputGroup>
            <Separator
                orientation="horizontal"
                data-slot="autocomplete-popover-separator"
                className="w-[calc(100%+var(--spacing))]"
            />
        </div>
    )
})

const AutocompleteContent = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.Popup>,
    AutocompletePrimitive.Popup.Props &
        Pick<AutocompletePrimitive.Positioner.Props, 'side' | 'align' | 'sideOffset' | 'alignOffset' | 'anchor'>
>(function AutocompleteContent(
    { className, side = 'bottom', sideOffset = 6, align = 'start', alignOffset = 0, anchor: anchorProp, ...props },
    ref
) {
    const contextAnchor = React.useContext(AutocompleteAnchorContext)
    const anchor = anchorProp ?? contextAnchor
    return (
        <AutocompletePrimitive.Portal>
            <AutocompletePrimitive.Positioner
                data-quill
                data-quill-portal="popover"
                side={side}
                sideOffset={sideOffset}
                align={align}
                alignOffset={alignOffset}
                anchor={anchor}
                className="isolate"
            >
                <AutocompletePrimitive.Popup
                    ref={ref}
                    data-slot="autocomplete-content"
                    className={cn('quill-autocomplete__content group/autocomplete-content', className)}
                    {...props}
                />
            </AutocompletePrimitive.Positioner>
        </AutocompletePrimitive.Portal>
    )
})

const AutocompleteList = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.List>,
    AutocompletePrimitive.List.Props
>(function AutocompleteList({ className, ...props }, ref) {
    return (
        <AutocompletePrimitive.List
            ref={ref}
            data-slot="autocomplete-list"
            className={cn(
                'quill-autocomplete__list scroll-mask-t-2 scroll-mask-b-4 scroll-pb-4 scroll-pt-6 empty:hidden',
                className
            )}
            {...props}
        />
    )
})

const AutocompleteItem = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.Item>,
    AutocompletePrimitive.Item.Props & { title?: string }
>(function AutocompleteItem({ className, children, title, ...props }, ref) {
    return (
        <AutocompletePrimitive.Item
            ref={ref}
            data-slot="autocomplete-item"
            className={cn('quill-autocomplete__item', className)}
            title={title ?? (typeof children === 'string' ? children : undefined)}
            render={
                <Button
                    size="row"
                    left
                    className="min-w-0 aria-selected:bg-fill-selected data-highlighted:border-ring data-highlighted:ring-2 data-highlighted:ring-ring/30 ring-offset-1"
                />
            }
            tabIndex={-1}
            {...props}
        >
            <span className="flex items-center gap-1.5 min-w-0 truncate">{children}</span>
        </AutocompletePrimitive.Item>
    )
})

const AutocompleteGroup = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.Group>,
    AutocompletePrimitive.Group.Props
>(function AutocompleteGroup({ className, ...props }, ref) {
    return (
        <AutocompletePrimitive.Group
            ref={ref}
            data-slot="autocomplete-group"
            className={cn('pb-1', className)}
            {...props}
        />
    )
})

const AutocompleteLabel = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.GroupLabel>,
    AutocompletePrimitive.GroupLabel.Props
>(function AutocompleteLabel({ className, ...props }, ref) {
    return (
        <AutocompletePrimitive.GroupLabel
            ref={ref}
            data-slot="autocomplete-label"
            className={cn('quill-autocomplete__label mb-1 -mx-1 w-[calc(100%+var(--spacing)*2)]', className)}
            render={<MenuLabel />}
            {...props}
        />
    )
})

function AutocompleteCollection({ ...props }: AutocompletePrimitive.Collection.Props): React.ReactElement {
    return <AutocompletePrimitive.Collection data-slot="autocomplete-collection" {...props} />
}

const AutocompleteEmpty = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.Empty>,
    AutocompletePrimitive.Empty.Props
>(function AutocompleteEmpty({ className, ...props }, ref) {
    // Base UI renders the children only when nothing matches, so `empty:hidden` is the whole visibility rule.
    return (
        <AutocompletePrimitive.Empty
            ref={ref}
            data-slot="autocomplete-empty"
            className={cn('empty:hidden', className)}
            render={<MenuEmpty />}
            {...props}
        />
    )
})

const AutocompleteSeparator = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.Separator>,
    AutocompletePrimitive.Separator.Props
>(function AutocompleteSeparator({ className, ...props }, ref) {
    return (
        <AutocompletePrimitive.Separator
            ref={ref}
            data-slot="autocomplete-separator"
            className={cn('quill-autocomplete__separator my-0', className)}
            {...props}
        />
    )
})

/**
 * Walks `useFilteredItems` output and returns the total leaf count.
 * Handles both flat arrays (returns `length`) and grouped arrays where
 * each entry has an `items` property (returns sum of all `.items.length`).
 */
function countAutocompleteLeaves(items: unknown): number {
    if (!Array.isArray(items)) {return 0}
    return items.reduce<number>((acc, item) => {
        if (item && typeof item === 'object' && 'items' in item && Array.isArray((item as { items: unknown[] }).items)) {
            return acc + (item as { items: unknown[] }).items.length
        }
        return acc + 1
    }, 0)
}

/**
 * Live region announcer that also renders visible status text. Default
 * content is "{count} results" pluralized; pass `emptyContent` to override
 * the zero-count state, or `children` (string / node / function) to fully
 * customize. `empty:hidden` collapses the element when there's nothing to
 * render so it doesn't take a row of space.
 *
 * Counts are derived via `Autocomplete.useFilteredItems()` from the parent
 * Root, so it works for flat *and* grouped item shapes.
 *
 * MUST be rendered inside `<Autocomplete>` — `useFilteredItems` reads from
 * Autocomplete's Root context and will throw if no provider is mounted.
 */
const AutocompleteStatus = React.forwardRef<
    React.ComponentRef<typeof AutocompletePrimitive.Status>,
    Omit<AutocompletePrimitive.Status.Props, 'children'> & {
        /**
         * Override the default "{count} results" rendering. Pass a function to
         * receive the count; pass a node to render statically.
         */
        children?: React.ReactNode | ((count: number) => React.ReactNode)
        /** Rendered when the filtered count is zero. */
        emptyContent?: React.ReactNode
    }
>(function AutocompleteStatus({ className, children, emptyContent, ...props }, ref) {
    const filtered = AutocompletePrimitive.useFilteredItems<unknown>()
    const count = countAutocompleteLeaves(filtered)

    let content: React.ReactNode
    if (typeof children === 'function') {
        content = children(count)
    } else if (children !== undefined) {
        content = children
    } else if (count === 0) {
        content = emptyContent
    } else {
        content = `${count} ${count === 1 ? 'result' : 'results'}`
    }

    return (
        <AutocompletePrimitive.Status
            ref={ref}
            data-slot="autocomplete-status"
            className={cn(
                'quill-autocomplete__status bg-card border-b border-border text-xs text-muted-foreground px-2 py-1.5 empty:hidden',
                className
            )}
            {...props}
        >
            {content}
        </AutocompletePrimitive.Status>
    )
})

/**
 * Hook returning the anchor ref so consumers (e.g. an external trigger)
 * can position the popup against an arbitrary element.
 */
function useAutocompleteAnchor(): React.RefObject<HTMLDivElement> {
    const contextRef = React.useContext(AutocompleteAnchorContext)
    if (contextRef === null) {
        throw new Error('useAutocompleteAnchor must be used within an Autocomplete')
    }
    return contextRef
}

export {
    Autocomplete,
    AutocompleteClear,
    AutocompleteCollection,
    AutocompleteContent,
    AutocompleteEmpty,
    AutocompleteGroup,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteLabel,
    AutocompleteList,
    AutocompleteSeparator,
    AutocompleteStatus,
    AutocompleteTrigger,
    AutocompleteValue,
    useAutocompleteAnchor,
}
