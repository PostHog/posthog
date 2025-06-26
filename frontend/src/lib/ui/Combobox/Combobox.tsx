import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'
import React, {
    createContext,
    forwardRef,
    ReactNode,
    useCallback,
    useContext,
    useEffect,
    useImperativeHandle,
    useMemo,
    useReducer,
    useRef,
    useState,
} from 'react'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { TextInputPrimitive } from '../TextInputPrimitive/TextInputPrimitive'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

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

const InnerCombobox = forwardRef<ListBoxHandle, ComboboxProps>(({ children, className, ...props }, ref) => {
    const listboxRef = useRef<ListBoxHandle>(null)
    const [searchValue, setSearchValue] = useState('')

    // Pure-react group visibility state
    type Action = { type: 'register'; id: string; visible: boolean } | { type: 'unregister'; id: string }

    type State = Map<string, boolean>

    const groupReducer = (state: State, action: Action): State => {
        const newState = new Map(state)

        switch (action.type) {
            case 'register': {
                newState.set(action.id, action.visible)
                return newState
            }
            case 'unregister': {
                newState.delete(action.id)
                return newState
            }
            default:
                return state
        }
    }

    const [groupVisibility, dispatch] = useReducer(groupReducer, new Map())

    const registerGroup = useCallback((id: string, visible: boolean): void => {
        dispatch({ type: 'register', id, visible })
    }, [])

    const unregisterGroup = useCallback((id: string): void => {
        dispatch({ type: 'unregister', id })
    }, [])

    const getVisibleGroupCount = useCallback((): number => {
        return Array.from(groupVisibility.values()).filter(Boolean).length
    }, [groupVisibility])

    const contextValue = useMemo(
        () => ({
            searchValue,
            setSearchValue,
            registerGroup,
            unregisterGroup,
            getVisibleGroupCount,
        }),
        [searchValue, registerGroup, unregisterGroup, getVisibleGroupCount]
    )

    useImperativeHandle(ref, () => ({
        recalculateFocusableElements: () => listboxRef.current?.recalculateFocusableElements(),
        focusFirstItem: () => listboxRef.current?.focusFirstItem(),
        getFocusableElementsCount: () => listboxRef.current?.getFocusableElementsCount() ?? 0,
    }))

    useEffect(() => {
        listboxRef.current?.recalculateFocusableElements()
        listboxRef.current?.focusFirstItem()
    }, [searchValue])

    return (
        <ComboboxContext.Provider value={contextValue}>
            <ListBox
                ref={listboxRef}
                className={className}
                {...props}
                virtualFocus
                role="listbox"
                id="combobox-listbox"
            >
                {children}
            </ListBox>
        </ComboboxContext.Provider>
    )
})

InnerCombobox.displayName = 'Combobox'

interface SearchProps {
    placeholder?: string
    className?: string
    autoFocus?: boolean
}

const Search = ({ placeholder = 'Search...', className, autoFocus = true }: SearchProps): JSX.Element => {
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
                autoFocus={autoFocus}
                role="combobox"
                aria-controls="combobox-listbox"
            />
        </div>
    )
}

let groupIdCounter = 0

interface GroupProps {
    value: string[]
    children: ReactNode
}

const Group = ({ value, children }: GroupProps): JSX.Element | null => {
    const context = useContext(ComboboxContext)
    if (!context) {
        throw new Error('Combobox.Group must be used inside Combobox')
    }

    const { searchValue, registerGroup, unregisterGroup } = context
    const idRef = useRef<string>(`group-${groupIdCounter++}`)

    const lowerSearch = searchValue.toLowerCase()
    const match = value.some((v) => v.toLowerCase().includes(lowerSearch))

    useEffect(() => {
        const id = idRef.current
        registerGroup(id, match)
        return () => {
            unregisterGroup(id)
        }
    }, [match, registerGroup, unregisterGroup])

    if (!match) {
        return null
    }

    return <div>{children}</div>
}

interface EmptyProps {
    children: ReactNode
}

const Empty = ({ children }: EmptyProps): JSX.Element | null => {
    const context = useContext(ComboboxContext)
    if (!context) {
        throw new Error('Combobox.Empty must be used inside Combobox')
    }

    return context.getVisibleGroupCount() === 0 ? (
        <ButtonPrimitive className="text-tertiary text-center" role="alert">
            {children}
        </ButtonPrimitive>
    ) : null
}

interface ContentProps {
    children: ReactNode
    className?: string
}

const Content = ({ className, children }: ContentProps): JSX.Element => {
    return (
        <div className={cn('primitive-menu-content max-h-[300px] max-w-none border-transparent', className)}>
            <ScrollableShadows
                direction="vertical"
                styledScrollbars
                innerClassName="primitive-menu-content-inner flex flex-col gap-px"
            >
                {children}
            </ScrollableShadows>
        </div>
    )
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
