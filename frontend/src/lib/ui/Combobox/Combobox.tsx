import React, {
    ReactNode,
    createContext,
    forwardRef,
    useCallback,
    useContext,
    useEffect,
    useImperativeHandle,
    useMemo,
    useReducer,
    useRef,
    useState,
} from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { TextInputPrimitive } from '../TextInputPrimitive/TextInputPrimitive'

interface ComboboxContextType {
    searchValue: string
    setSearchValue: (value: string) => void
    registerGroup: (id: string, visible: boolean, isSearchable?: boolean) => void
    unregisterGroup: (id: string) => void
    getVisibleSearchableGroupCount: () => number
    insideMenu?: boolean
}

const ComboboxContext = createContext<ComboboxContextType | null>(null)

interface ComboboxProps extends React.HTMLAttributes<HTMLDivElement> {
    children: ReactNode
    insideMenu?: boolean
}

type Action =
    | { type: 'register'; id: string; visible: boolean; isSearchable?: boolean }
    | { type: 'unregister'; id: string }

type State = Map<string, { visible: boolean; isSearchable: boolean }>

const InnerCombobox = forwardRef<ListBoxHandle, ComboboxProps>(
    ({ children, className, insideMenu = false, ...props }, ref) => {
        const listboxRef = useRef<ListBoxHandle>(null)
        const [searchValue, setSearchValue] = useState('')

        const groupReducer = (state: State, action: Action): State => {
            const newState = new Map(state)

            switch (action.type) {
                case 'register': {
                    newState.set(action.id, {
                        visible: action.visible,
                        isSearchable: action.isSearchable ?? true,
                    })
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

        const registerGroup = useCallback((id: string, visible: boolean, isSearchable = true): void => {
            dispatch({ type: 'register', id, visible, isSearchable })
        }, [])

        const unregisterGroup = useCallback((id: string): void => {
            dispatch({ type: 'unregister', id })
        }, [])

        const getVisibleSearchableGroupCount = useCallback((): number => {
            return Array.from(groupVisibility.values()).filter((group) => group.visible && group.isSearchable).length
        }, [groupVisibility])

        const contextValue = useMemo(
            () => ({
                searchValue,
                setSearchValue,
                registerGroup,
                unregisterGroup,
                getVisibleSearchableGroupCount,
                insideMenu,
            }),
            [searchValue, registerGroup, unregisterGroup, getVisibleSearchableGroupCount, insideMenu]
        )

        useImperativeHandle(ref, () => ({
            recalculateFocusableElements: () => listboxRef.current?.recalculateFocusableElements(),
            focusFirstItem: () => listboxRef.current?.focusFirstItem(),
            getFocusableElementsCount: () => listboxRef.current?.getFocusableElementsCount() ?? 0,
            focusItemByKey: (key: string) => listboxRef.current?.focusItemByKey(key) ?? false,
            focusPrevious: (stepsBack?: number) => listboxRef.current?.focusPrevious(stepsBack) ?? false,
            getFocusHistory: () => listboxRef.current?.getFocusHistory() ?? [],
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
                    style={
                        {
                            // Match text input base height with p-1 padding
                            '--combobox-search-height': 'calc(var(--text-input-height-base) + (var(--spacing) * 2))',
                        } as React.CSSProperties
                    }
                >
                    {children}
                </ListBox>
            </ComboboxContext.Provider>
        )
    }
)

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
        <div className={cn('p-1', context.insideMenu && 'px-0 pt-0')}>
            <TextInputPrimitive
                type="text"
                value={context.searchValue}
                onChange={(e) => context.setSearchValue(e.target.value)}
                className={cn(className, 'w-full')}
                placeholder={placeholder}
                autoFocus={autoFocus}
                role="combobox"
                size="default"
                aria-controls="combobox-listbox"
            />
        </div>
    )
}

let groupIdCounter = 0

interface GroupProps {
    value?: string[]
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
    const match = !value?.length || value.some((v) => v.toLowerCase().includes(lowerSearch))
    const isSearchable = !!value?.length

    useEffect(() => {
        const id = idRef.current
        registerGroup(id, match, isSearchable)
        return () => {
            unregisterGroup(id)
        }
    }, [match, isSearchable, registerGroup, unregisterGroup])

    if (!match) {
        return null
    }

    return <div className="contents">{children}</div>
}

interface EmptyProps {
    children: ReactNode
}

const Empty = ({ children }: EmptyProps): JSX.Element | null => {
    const context = useContext(ComboboxContext)
    if (!context) {
        throw new Error('Combobox.Empty must be used inside Combobox')
    }

    return context.getVisibleSearchableGroupCount() === 0 ? (
        <ButtonPrimitive className="text-tertiary text-center" role="alert" menuItem inert>
            {children}
        </ButtonPrimitive>
    ) : null
}

interface ContentProps {
    children: ReactNode
    className?: string
}

const Content = ({ className, children }: ContentProps): JSX.Element => {
    const context = useContext(ComboboxContext)
    if (!context) {
        throw new Error('Combobox.Content must be used inside Combobox')
    }

    return (
        <ScrollableShadows
            direction="vertical"
            styledScrollbars
            className={cn(
                'max-h-[calc(var(--radix-popover-content-available-height)-var(--combobox-search-height)-var(--radix-popper-anchor-height))] max-w-none border-transparent overflow-y-auto',
                className
            )}
            innerClassName={cn('flex flex-col gap-px p-1', context.insideMenu && 'px-0 pb-0')}
        >
            {children}
        </ScrollableShadows>
    )
}

/** Compound type augmentation */
export type ComboboxType = React.ForwardRefExoticComponent<ComboboxProps & React.RefAttributes<ListBoxHandle>> & {
    Search: typeof Search
    Group: typeof Group
    Empty: typeof Empty
    Content: typeof Content
    Item: typeof ListBox.Item
    ListGroup: typeof ListBox.Group
}
;(InnerCombobox as ComboboxType).Search = Search
;(InnerCombobox as ComboboxType).Group = Group
;(InnerCombobox as ComboboxType).Empty = Empty
;(InnerCombobox as ComboboxType).Content = Content
;(InnerCombobox as ComboboxType).Item = ListBox.Item
;(InnerCombobox as ComboboxType).ListGroup = ListBox.Group

export const Combobox = InnerCombobox as ComboboxType
