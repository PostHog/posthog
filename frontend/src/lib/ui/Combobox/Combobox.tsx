import { cva, type VariantProps } from 'cva'
import { cn } from 'lib/utils/css-classes'
import React, {
    createContext,
    forwardRef,
    ReactNode,
    useContext,
    useEffect,
    useRef,
    useState
} from 'react'
import { ListBox, ListBoxHandle } from '../ListBox/ListBox'
import { TextInputPrimitive } from '../TextInputPrimitive/TextInputPrimitive'

// Styling variants
const comboboxVariants = cva({
    base: 'w-full border-primary bg-surface-primary hover:border-tertiary rounded border border-primary p-2 text-sm',
})

// Context for shared state
type ComboboxContextValue = {
    value: string
    setValue: (value: string) => void
}

const ComboboxContext = createContext<ComboboxContextValue | null>(null)

const useComboboxContext = () => {
    const context = useContext(ComboboxContext)
    if (!context) {
        throw new Error('Combobox components must be used inside <Combobox>')
    }
    return context
}

// Root Combobox
type ComboboxBaseProps = {
    className?: string
    children: ReactNode
} & VariantProps<typeof comboboxVariants>

export const Combobox = forwardRef<HTMLDivElement, ComboboxBaseProps>(
    ({ className, children }, ref) => {
        const [value, setValue] = useState('')
        const listBoxRef = useRef<ListBoxHandle>(null)

        useEffect(() => {
            listBoxRef.current?.focusFirstItem()
        }, [value])

        return (
            <ComboboxContext.Provider value={{ value, setValue }}>
                <div ref={ref} className={cn('w-full', className)}>
                    <ListBox ref={listBoxRef} className="w-full" virtualFocus>
                        {children}
                    </ListBox>
                </div>
            </ComboboxContext.Provider>
        )
    }
)

Combobox.displayName = 'Combobox'

// Search Input
type ComboboxSearchProps = {
    autoFocus?: boolean
    placeholder?: string
    className?: string
}

export const ComboboxSearch = forwardRef<HTMLInputElement, ComboboxSearchProps>(
    ({ autoFocus, placeholder, className }, ref) => {
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
    }
)

ComboboxSearch.displayName = 'ComboboxSearch'

// Content (filters children)
type ComboboxContentProps = {
    children: ReactNode
    className?: string
}

export const ComboboxContent = ({ children, className }: ComboboxContentProps) => {
    const { value } = useComboboxContext()

    const filteredItems = React.Children.toArray(children).filter((child) => {
        if (!React.isValidElement(child)) return false

        if (child.type === ComboboxItem) {
            const text = extractTextFromReactNode(child.props.children).toLowerCase()
            return text.includes(value.toLowerCase())
        }

        return true
    })

    return (
        <ul className={cn('flex flex-col gap-px px-1 pb-1', className)}>
            {filteredItems}
        </ul>
    )
}

ComboboxContent.displayName = 'ComboboxContent'

// Item
type ComboboxItemProps = React.ComponentPropsWithoutRef<typeof ListBox.Item>

export const ComboboxItem = forwardRef<React.ElementRef<typeof ListBox.Item>, ComboboxItemProps>(
    (props, ref) => <ListBox.Item {...props} ref={ref} />
)

ComboboxItem.displayName = 'ComboboxItem'

// Helper to extract text from any nested child for filtering
function extractTextFromReactNode(node: ReactNode): string {
    if (typeof node === 'string' || typeof node === 'number') {
        return node.toString()
    }

    if (Array.isArray(node)) {
        return node.map(extractTextFromReactNode).join('')
    }

    if (React.isValidElement(node)) {
        return extractTextFromReactNode(node.props.children)
    }

    return ''
}

/** ✅ Example usage:

<Combobox>
    <ComboboxSearch placeholder="Search..." />

    <ComboboxContent>
        <ComboboxItem asChild aria-disabled="true">
            <ButtonPrimitive menuItem disabled>
                <IconSearch className="size-4" />
                Search icon
            </ButtonPrimitive>
        </ComboboxItem>

        <ComboboxItem asChild>
            <ButtonPrimitive menuItem>Item 1</ButtonPrimitive>
        </ComboboxItem>

        <ComboboxItem asChild>
            <ButtonPrimitive menuItem>Item 2</ButtonPrimitive>
        </ComboboxItem>
    </ComboboxContent>
</Combobox>

**/
