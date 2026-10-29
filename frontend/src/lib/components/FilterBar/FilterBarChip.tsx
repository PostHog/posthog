import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    ButtonGroupText,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuFilterProvider,
    DropdownMenuInput,
    DropdownMenuTrigger,
    cn,
} from '@posthog/quill'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyFilterType } from '~/types'

import { categoryIdForFilter } from './filterBarCategories'
import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import {
    fieldFromFilter,
    groupTypeIndexForCategory,
    operatorLabelForFilter,
    propertyDefinitionTypeForCategory,
    valueKindForFilter,
    valueLabelForFilter,
} from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarOperatorRadioItems } from './FilterBarOperatorRadioItems'
import { FilterBarItem } from './filterBarTypes'
import { FilterBarValueRows } from './FilterBarValueRows'

/**
 * One filter as a segmented chip: the field, the operator, the value, and a remove button. The operator and value
 * segments open menus, so a filter is edited in place.
 */
export function FilterBarChip({ item }: { item: FilterBarItem }): JSX.Element | null {
    const { cohortsById } = useValues(cohortsModel)
    const { describeProperty } = useValues(propertyDefinitionsModel)
    const { removeItem, commitItem, loadItemValues, openSqlDialog } = useActions(filterBarLogic)
    const [valueQuery, setValueQuery] = useState('')
    const { filter } = item
    const field = fieldFromFilter(filter)
    if (!field) {
        return null
    }
    const categoryId = categoryIdForFilter(filter)
    const propertyType = categoryId
        ? describeProperty(
              filter.key ?? '',
              propertyDefinitionTypeForCategory(categoryId),
              groupTypeIndexForCategory(categoryId)
          )
        : null
    const kind = valueKindForFilter(filter, propertyType)
    const value = valueLabelForFilter(filter, cohortsById)
    const isSql = filter.type === PropertyFilterType.HogQL

    return (
        <ButtonGroup className="max-w-full" data-attr="filter-bar-chip">
            <ButtonGroupText className="min-w-0 border border-border px-2">
                <FilterBarCategoryIcon categoryId={field.categoryId} className="shrink-0" />
                <span className="truncate">{isSql ? 'SQL' : field.label}</span>
            </ButtonGroupText>
            {!isSql && (
                <DropdownMenu modal={false}>
                    <DropdownMenuTrigger
                        render={<Button variant="outline" className="text-muted-foreground" />}
                        data-attr="filter-bar-chip-operator"
                    >
                        {operatorLabelForFilter(filter)}
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                        <FilterBarOperatorRadioItems item={item} propertyType={propertyType} />
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            {isSql ? (
                <Button
                    variant="outline"
                    className="min-w-0 max-w-96 font-mono"
                    onClick={() => openSqlDialog(item.id)}
                    data-attr="filter-bar-chip-value"
                >
                    <span className="truncate">{value.text}</span>
                </Button>
            ) : (
                kind !== 'none' && (
                    <DropdownMenuFilterProvider
                        filter={null}
                        value={valueQuery}
                        onValueChange={(query) => {
                            setValueQuery(query)
                            loadItemValues(item.id, query)
                        }}
                        autoHighlight
                    >
                        <DropdownMenu
                            modal={false}
                            onOpenChange={(open) => {
                                if (open) {
                                    loadItemValues(item.id, '')
                                } else {
                                    commitItem(item.id)
                                }
                            }}
                        >
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        className={cn('min-w-0 max-w-64', value.placeholder && 'text-muted-foreground')}
                                    />
                                }
                                data-attr="filter-bar-chip-value"
                            >
                                <span className="truncate">{value.text}</span>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                                className="w-72"
                                header={
                                    <DropdownMenuInput
                                        aria-label="Search or type a value"
                                        placeholder={`${field.label}…`}
                                    />
                                }
                            >
                                <FilterBarValueRows item={item} query={valueQuery} />
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </DropdownMenuFilterProvider>
                )
            )}
            <Button
                size="icon"
                variant="outline"
                aria-label={`Remove ${field.label} filter`}
                tooltip="Remove filter"
                onClick={() => removeItem(item.id)}
                data-attr="filter-bar-chip-remove"
            >
                <IconX />
            </Button>
        </ButtonGroup>
    )
}
