import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { Button, ButtonGroup, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType } from '~/types'

import { type FilterControlProps, INCOMPLETE_LABEL } from '../filterDefinition'
import { FilterPillContent } from '../FilterPillContent'
import { ConditionEditor } from './ConditionEditor'
import type { PropertyFilterConfig, PropertyFilterValue, PropertyValues } from './propertyFilterSpec'
import { type PropertyCondition, describeCondition, isCompleteCondition, operatorsFor } from './propertyOperators'
import { useConditionDrafts } from './useConditionDrafts'

function summary(conditions: PropertyCondition[]): JSX.Element | undefined {
    if (conditions.length === 0) {
        return undefined
    }
    if (conditions.length > 1) {
        return <span>{conditions.length} conditions</span>
    }
    const shown = describeCondition(conditions[0])
    return (
        <>
            <span className="text-secondary">{shown.operator}</span>
            {shown.value}
        </>
    )
}

export function PropertyFilter({
    filter,
    value = [],
    onChange,
    defaultOpen,
    values,
}: FilterControlProps<PropertyFilterConfig, PropertyFilterValue> & { values?: PropertyValues }): JSX.Element {
    const { describeProperty } = useValues(propertyDefinitionsModel)
    const { key, source } = filter.config
    const loadValues = useMemo(
        () => (values ? (search: string, signal: AbortSignal) => values({ key, source }, search, signal) : undefined),
        [values, key, source]
    )
    const options = operatorsFor(
        describeProperty(key, source === 'person' ? PropertyDefinitionType.Person : PropertyDefinitionType.Event)
    )
    const { drafts, editing, edit, editFirstIncomplete, change, add, remove } = useConditionDrafts(
        value,
        options[0].operator,
        onChange
    )
    const [open, setOpen] = useState(!!defaultOpen)
    const changeOpen = (next: boolean): void => {
        setOpen(next)
        // Conditions apply as they are picked, so reopening shows them folded unless one still needs a value.
        if (next) {
            editFirstIncomplete()
        }
    }

    return (
        <Popover open={open} onOpenChange={changeOpen}>
            <PopoverTrigger render={<Button size="sm" variant="outline" data-attr="dashboard-v2-filter-property" />}>
                <FilterPillContent label={filter.label ?? key} summary={summary(value)} />
            </PopoverTrigger>
            <PopoverContent align="start" className="flex w-96 flex-col gap-2 p-2">
                <span className="truncate text-xs font-medium">{filter.label ?? key}</span>
                {drafts.map((draft, index) => (
                    // The joining word sits beside its condition, so the list reads top to bottom as one sentence.
                    <div key={draft.id} className="flex items-start gap-2">
                        <span className="w-9 shrink-0 pt-1 text-right text-xs text-muted-foreground">
                            {index === 0 ? 'where' : 'and'}
                        </span>
                        <div className="flex min-w-0 flex-1 flex-col gap-2">
                            {draft.id === editing ? (
                                <ConditionEditor
                                    options={options}
                                    draft={draft}
                                    loadValues={loadValues}
                                    onChange={change}
                                />
                            ) : (
                                <ButtonGroup className="w-full">
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        className="min-w-0 flex-1 justify-start"
                                        data-attr="dashboard-v2-filter-condition"
                                        onClick={() => edit(draft.id)}
                                    >
                                        {summary(isCompleteCondition(draft) ? [draft] : []) ?? (
                                            <span className="text-tertiary">{INCOMPLETE_LABEL}</span>
                                        )}
                                    </Button>
                                    <Button
                                        size="icon-sm"
                                        variant="outline"
                                        aria-label="Remove condition"
                                        tooltip="Remove condition"
                                        onClick={() => remove(draft.id)}
                                    >
                                        <IconX />
                                    </Button>
                                </ButtonGroup>
                            )}
                        </div>
                    </div>
                ))}
                <div className="ml-11 flex items-center justify-between gap-2">
                    <Button
                        size="sm"
                        data-attr="dashboard-v2-filter-add-condition"
                        disabledReason={drafts.every(isCompleteCondition) ? undefined : 'Finish this condition first'}
                        onClick={add}
                    >
                        <IconPlus />
                        And
                    </Button>
                    <Button
                        size="sm"
                        variant="primary"
                        data-attr="dashboard-v2-filter-done"
                        onClick={() => changeOpen(false)}
                    >
                        Done
                    </Button>
                </div>
            </PopoverContent>
        </Popover>
    )
}
