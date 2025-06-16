import { cva, type VariantProps } from 'cva'
import { cn } from 'lib/utils/css-classes'
import React, {
    createContext,
    forwardRef,
    isValidElement,
    ReactNode,
    useContext,
    useEffect,
    useRef,
    useState
} from 'react'
import { ListBox, ListBoxHandle } from '../ListBox/ListBox'
import { TextInputPrimitive } from '../TextInputPrimitive/TextInputPrimitive'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

/* ─────────────────────────────────────────── Styling ─────────────────────────────────────────── */

const comboboxVariants = cva({
    base: 'w-full border-primary bg-surface-primary hover:border-tertiary rounded border border-primary p-2 text-sm',
})

/* ─────────────────────────────────────────── Context ─────────────────────────────────────────── */

type ComboboxCtx = { value: string; setValue: (v: string) => void }
const ComboboxContext = createContext<ComboboxCtx | null>(null)
const useComboboxContext = () => {
    const ctx = useContext(ComboboxContext)
    if (!ctx) throw new Error('Combobox components must be used within <Combobox>')
    return ctx
}

/* ─────────────────────────────────────────── Root ─────────────────────────────────────────── */

type ComboboxProps = VariantProps<typeof comboboxVariants> & {
    className?: string
    children: ReactNode
}

export const Combobox = forwardRef<HTMLDivElement, ComboboxProps>(function Combobox(
    { children, className },
    ref
) {
    const [value, setValue] = useState('')
    const listboxRef = useRef<ListBoxHandle>(null)

    useEffect(() => listboxRef.current?.focusFirstItem(), [value])

    return (
        <ComboboxContext.Provider value={{ value, setValue }}>
            <div ref={ref} className={cn('w-full', className)}>
                <ListBox ref={listboxRef} className="w-full flex flex-col gap-px" virtualFocus>
                    {children}
                </ListBox>
            </div>
        </ComboboxContext.Provider>
    )
})

/* ─────────────────────────────────────────── Search ─────────────────────────────────────────── */

type ComboboxSearchProps = {
    autoFocus?: boolean
    placeholder?: string
    className?: string
}

export const ComboboxSearch = forwardRef<HTMLInputElement, ComboboxSearchProps>(function ComboboxSearch(
    { autoFocus, placeholder, className },
    ref
) {
    const { value, setValue } = useComboboxContext()
    return (
        <div className="p-1">
            <ListBox.Item asChild virtualFocusIgnore>
                <TextInputPrimitive
                    ref={ref}
                    autoFocus={autoFocus}
                    placeholder={placeholder}
                    className={cn(comboboxVariants({ className }))}
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                />
            </ListBox.Item>
        </div>
    )
})

/* ─────────────────────────────────────────── Subcomponents ─────────────────────────────────────────── */

export const ComboboxGroup = ({ children }: { children: ReactNode }) => <>{children}</>

type ItemBase = React.ComponentPropsWithoutRef<typeof ListBox.Item>
export interface ComboboxItemProps extends ItemBase {
    alwaysVisible?: boolean
    filterValue?: string
}
export const ComboboxItem = forwardRef<React.ElementRef<typeof ListBox.Item>, ComboboxItemProps>(
    (props, ref) => <ListBox.Item {...props} ref={ref} />
)

export const ComboboxEmpty = ({ children, className }: { children: ReactNode; className?: string }) => (
    <div className={cn('px-2 py-1 text-sm text-muted-foreground', className)}>{children}</div>
)

export const ComboboxFooter = ({ children, className }: { children: ReactNode; className?: string }) => (
    <div className={cn('px-1 pb-1', className)}>{children}</div>
)

/* ─────────────────────────────────────────── Content ─────────────────────────────────────────── */

export const ComboboxContent = ({ children, className }: { children: ReactNode; className?: string }) => {
    const { value } = useComboboxContext()
    const trimmedValue = value.trim().toLowerCase()

    const filtered = trimmedValue === '' ? children : filterComboboxChildren(children, trimmedValue)
    const pruned = pruneEmptyContainers(filtered)
    const anyVisible = hasAnyVisibleComboboxItem(pruned)
    const showEmpty = trimmedValue.length > 0 && !anyVisible

    return (
        <ul className={cn('flex flex-col gap-px p-1', className)}>
            <ScrollableShadows direction="vertical" styledScrollbars innerClassName="flex flex-col gap-px">
                {showEmpty ? extractComboboxEmpty(children) : pruned}
            </ScrollableShadows>
        </ul>
    )
}

/* ─────────────────────────────────────────── Helpers ─────────────────────────────────────────── */

const isElem = (c: ReactNode): c is React.ReactElement => isValidElement(c)
const isItem = (c: ReactNode) => isElem(c) && c.type === ComboboxItem
const isGroup = (c: ReactNode) => isElem(c) && c.type === ComboboxGroup
const isEmptyNode = (c: ReactNode) => isElem(c) && c.type === ComboboxEmpty

function extractText(node: ReactNode): string {
    if (node == null) return ''
    if (typeof node === 'string' || typeof node === 'number') return String(node)
    if (Array.isArray(node)) return node.map(extractText).join('')
    return isElem(node) ? extractText(node.props.children) : ''
}

/* -- Filtering Pass -- */

function filterComboboxChildren(children: ReactNode, searchValue: string): ReactNode {
    return React.Children.map(children, (child) => {
        if (!isValidElement(child)) return child

        if (isGroup(child)) {
            const filteredChildren = filterComboboxChildren(child.props.children, searchValue)
            return React.cloneElement(child, { ...child.props, children: filteredChildren })
        }

        if (isItem(child)) {
            if (child.props.alwaysVisible) return child

            const filterText = child.props.filterValue ?? extractText(child.props.children)
            return filterText.toLowerCase().includes(searchValue) ? child : null
        }

        if (child.props?.children) {
            const filteredNested = filterComboboxChildren(child.props.children, searchValue)
            return React.cloneElement(child, { ...child.props, children: filteredNested })
        }

        return child
    })
}

/* -- Prune Pass -- */

function pruneEmptyContainers(children: ReactNode): ReactNode {
    return React.Children.map(children, (child) => {
        if (!isValidElement(child)) return child

        if (isItem(child) || isEmptyNode(child)) return child

        const prunedChildren = pruneEmptyContainers(child.props.children)
        const hasRemaining = React.Children.toArray(prunedChildren).some(Boolean)

        if (!hasRemaining) return null

        return React.cloneElement(child, { ...child.props, children: prunedChildren })
    })
}

/* -- Visible Check -- */

function hasAnyVisibleComboboxItem(children: ReactNode): boolean {
    let found = false

    React.Children.forEach(children, (child) => {
        if (found) return
        if (!isValidElement(child)) return

        if (isItem(child)) {
            found = true
        } else if (child.props?.children) {
            if (hasAnyVisibleComboboxItem(child.props.children)) {
                found = true
            }
        }
    })

    return found
}

/* -- Declarative Empty Extraction -- */

function extractComboboxEmpty(children: ReactNode): ReactNode {
    let res: ReactNode = null
    React.Children.forEach(children, (child) => {
        if (res) return
        if (!isValidElement(child)) return
        if (isEmptyNode(child)) res = child
        else if (child.props?.children) res = extractComboboxEmpty(child.props.children)
    })
    return res
}
