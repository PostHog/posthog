import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxSeparator,
    SelectTriggerIcon,
    Spinner,
} from '@posthog/quill'

import { ListVariable } from '../../types'
import { inlineListVariableSelectLogic } from './inlineListVariableSelectLogic'
import { useListVariableOptions } from './useListVariableOptions'
import { getListVariableSelectedValues } from './variableUtils'

// Objects, not strings, so no option value can be mistaken for an action row.
const CLEAR = { action: 'Clear selection' } as const
const SELECT_ALL = { action: 'Select all' } as const
const RELOAD = { action: 'Reload options' } as const
type Action = typeof CLEAR | typeof SELECT_ALL | typeof RELOAD
type Item = string | Action

interface ListGroup {
    value: string
    items: Item[]
}

interface QuillListVariableSelectProps {
    variable: ListVariable
    onChange: (variableId: string, value: string | string[], isNull: boolean) => void
}

export function QuillListVariableSelect({ variable, onChange }: QuillListVariableSelectProps): JSX.Element {
    const committedValues = variable.isNull ? [] : getListVariableSelectedValues(variable)
    const multiLogic = inlineListVariableSelectLogic({
        variableId: variable.id,
        selectedValues: committedValues,
        onChange: (values) => onChange(variable.id, values, values.length === 0),
    })
    const { selectedValues: bufferedValues } = useValues(multiLogic)
    const { commitSelectedValues, setSelectedValues } = useActions(multiLogic)
    const { options, error, loading, reload } = useListVariableOptions(variable, true)
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const triggerRef = useRef<HTMLButtonElement>(null)

    const selectedValues = variable.is_multi ? bufferedValues : committedValues
    const labelByValue = new Map(options.map((option) => [option.value, option.label]))
    const labelOf = (value: string): string => labelByValue.get(value) ?? value
    const query = search.trim().toLowerCase()
    const optionItems = options
        .filter((option) => !query || `${option.label} ${option.value}`.toLowerCase().includes(query))
        .map((option) => option.value)
    const actions: Action[] = [
        ...(selectedValues.length > 0 ? [CLEAR] : []),
        ...(variable.is_multi && options.some((option) => !selectedValues.includes(option.value)) ? [SELECT_ALL] : []),
        ...(variable.values_query?.trim() ? [RELOAD] : []),
    ]
    // Without options the list is empty, so the empty state can say whether they are loading or failed.
    const groups: ListGroup[] =
        optionItems.length > 0
            ? [
                  { value: 'options', items: optionItems },
                  ...(actions.length > 0 ? [{ value: 'actions', items: actions }] : []),
              ]
            : []

    const setPickerOpen = (next: boolean): void => {
        setOpen(next)
        if (!next) {
            setSearch('')
            if (variable.is_multi) {
                commitSelectedValues()
            }
        }
    }

    const runAction = (action: Action): void => {
        if (action === RELOAD) {
            reload()
        } else if (action === SELECT_ALL) {
            setSelectedValues(options.map((option) => option.value))
        } else if (variable.is_multi) {
            setSelectedValues([])
        } else {
            onChange(variable.id, '', true)
            setPickerOpen(false)
        }
    }

    const onValueChange = (next: Item | Item[] | null): void => {
        const picked = Array.isArray(next) ? next : next === null ? [] : [next]
        const action = picked.find((item): item is Action => typeof item !== 'string')
        if (action) {
            runAction(action)
            return
        }
        const values = picked as string[]
        if (variable.is_multi) {
            setSelectedValues(values)
        } else {
            onChange(variable.id, values[0] ?? '', values.length === 0)
            setPickerOpen(false)
        }
    }

    const display =
        selectedValues.length === 0
            ? null
            : variable.is_multi && selectedValues.length > 1
              ? `${selectedValues.length} selected`
              : labelOf(selectedValues[0])

    return (
        <Combobox<Item, boolean>
            items={groups}
            filter={null}
            multiple={Boolean(variable.is_multi)}
            autoHighlight
            open={open}
            onOpenChange={setPickerOpen}
            value={variable.is_multi ? selectedValues : (selectedValues[0] ?? null)}
            onValueChange={onValueChange}
            inputValue={search}
            onInputValueChange={setSearch}
            itemToStringLabel={(item: Item) => (typeof item === 'string' ? labelOf(item) : item.action)}
        >
            <Button
                ref={triggerRef}
                variant="outline"
                className="min-w-32 max-w-80 justify-between"
                onClick={() => setPickerOpen(!open)}
            >
                <span className={display ? 'min-w-0 truncate' : 'min-w-0 truncate text-muted-foreground'}>
                    {display ?? (loading ? 'Loading options...' : 'Select a value')}
                </span>
                <SelectTriggerIcon />
            </Button>
            <ComboboxContent anchor={triggerRef} className="w-72">
                <ComboboxInput placeholder="Search options..." showTrigger={false} />
                <ComboboxEmpty>
                    {loading ? (
                        <span className="flex items-center gap-2">
                            <Spinner />
                            Loading options...
                        </span>
                    ) : error ? (
                        "Couldn't load options. Check the query, then try again."
                    ) : (
                        'No matching options'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(group: ListGroup) => (
                        <ComboboxGroup key={group.value} items={group.items}>
                            {group.value === 'actions' && <ComboboxSeparator />}
                            <ComboboxCollection>
                                {(item: Item) =>
                                    typeof item === 'string' ? (
                                        <ComboboxItem key={item} value={item}>
                                            <span className="ph-no-capture min-w-0 truncate">{labelOf(item)}</span>
                                        </ComboboxItem>
                                    ) : (
                                        <ComboboxItem key={item.action} value={item} action>
                                            {item === RELOAD && loading ? (
                                                <span className="flex items-center gap-2">
                                                    <Spinner />
                                                    {item.action}
                                                </span>
                                            ) : (
                                                item.action
                                            )}
                                        </ComboboxItem>
                                    )
                                }
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
