import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'
import React, {
    createContext,
    forwardRef,
    ReactNode,
    useContext,
    useEffect,
    useImperativeHandle,
    useRef,
    useState,
} from 'react'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { TextInputPrimitive } from '../TextInputPrimitive/TextInputPrimitive'

interface ComboboxContextType {
    searchValue: string
    setSearchValue: (value: string) => void
    registerGroup: (id: string, visible: boolean) => void
    unregisterGroup: (id: string) => void
    getVisibleGroupCount: () => number
}

const ComboboxContext = createContext<ComboboxContextType | null>(null)

interface ComboboxProps extends React.HTMLAttributes<HTMLDivElement> {
    children: ReactNode
}

interface SearchProps {
    placeholder?: string
    className?: string
    autoFocus?: boolean
}

interface GroupProps {
    value: string[]
    children: ReactNode
}

interface EmptyProps {
    children: ReactNode
}

interface ContentProps {
    children: ReactNode
    className?: string
}

/** Main Combobox implementation */
const InnerCombobox = forwardRef<ListBoxHandle, ComboboxProps>(function Combobox(
    { children, className, ...props },
    ref
) {
    const listboxRef = useRef<ListBoxHandle>(null)
    const [searchValue, setSearchValue] = useState('')
    const groupVisibility = useRef<Map<string, boolean>>(new Map())
    const [, forceUpdate] = useState(0)

    useImperativeHandle(ref, () => ({
        recalculateFocusableElements: () => listboxRef.current?.recalculateFocusableElements(),
        focusFirstItem: () => listboxRef.current?.focusFirstItem(),
        getFocusableElementsCount: () => listboxRef.current?.getFocusableElementsCount() ?? 0,
    }))

    useEffect(() => {
        listboxRef.current?.recalculateFocusableElements()
        listboxRef.current?.focusFirstItem()
    }, [searchValue])

    const registerGroup = (id: string, visible: boolean): void => {
        groupVisibility.current.set(id, visible)
        forceUpdate((n) => n + 1)
    }

    const unregisterGroup = (id: string): void => {
        groupVisibility.current.delete(id)
        forceUpdate((n) => n + 1)
    }

    const getVisibleGroupCount = (): number => {
        return Array.from(groupVisibility.current.values()).filter(Boolean).length
    }

    return (
        <ComboboxContext.Provider
            value={{ searchValue, setSearchValue, registerGroup, unregisterGroup, getVisibleGroupCount }}
        >
            <ListBox ref={listboxRef} className={className} {...props} virtualFocus>
                {children}
            </ListBox>
        </ComboboxContext.Provider>
    )
})

InnerCombobox.displayName = 'Combobox'

/** Compound subcomponents */
const Search: React.FC<SearchProps> = ({ placeholder = 'Search...', className, autoFocus = true }) => {
    const context = useContext(ComboboxContext)
    if (!context) {
        throw new Error('Combobox.Search must be used inside Combobox')
    }

    return (
        <div className="p-1">
            <TextInputPrimitive
                type="text"
                value={context.searchValue}
                onChange={(e) => context.setSearchValue(e.target.value)}
                className={className}
                placeholder={placeholder}
                size="sm"
                autoFocus={autoFocus}
                role="combobox"
                aria-controls="combobox-listbox"
            />
        </div>
    )
}

let groupIdCounter = 0

const Group: React.FC<GroupProps> = ({ value, children }) => {
    const context = useContext(ComboboxContext)
    if (!context) {
        throw new Error('Combobox.Group must be used inside Combobox')
    }

    const idRef = useRef<string>(`group-${groupIdCounter++}`)

    const lowerSearch = context.searchValue.toLowerCase()
    const match = value.some((v) => v.toLowerCase().includes(lowerSearch))

    useEffect(() => {
        context.registerGroup(idRef.current, match)
        return () => {
            context.unregisterGroup(idRef.current)
        }
    }, [match, context])

    if (!match) {
        return null
    }

    return <div>{children}</div>
}

const Empty: React.FC<EmptyProps> = ({ children }) => {
    const context = useContext(ComboboxContext)
    if (!context) {
        throw new Error('Combobox.Empty must be used inside Combobox')
    }

    return context.getVisibleGroupCount() === 0 ? (
        <ButtonPrimitive className="text-tertiary text-center">{children}</ButtonPrimitive>
    ) : null
}

const Content: React.FC<ContentProps> = ({ className, children }) => {
    return <div className={cn('flex flex-col gap-px px-1 pb-1 overflow-y-auto', className)}>{children}</div>
}

/** Compound type augmentation */
export type ComboboxType = React.ForwardRefExoticComponent<ComboboxProps & React.RefAttributes<ListBoxHandle>> & {
    Search: typeof Search
    Group: typeof Group
    Empty: typeof Empty
    Content: typeof Content
    Item: typeof ListBox.Item
}
;(InnerCombobox as ComboboxType).Search = Search
;(InnerCombobox as ComboboxType).Group = Group
;(InnerCombobox as ComboboxType).Empty = Empty
;(InnerCombobox as ComboboxType).Content = Content
;(InnerCombobox as ComboboxType).Item = ListBox.Item

export const Combobox = InnerCombobox as ComboboxType
