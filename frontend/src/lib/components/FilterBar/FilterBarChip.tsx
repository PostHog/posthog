import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuFilterProvider,
    DropdownMenuInput,
    DropdownMenuTrigger,
    cn,
} from '@posthog/quill'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { FilterLogicalOperator, PropertyFilterType } from '~/types'

import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import { FilterBarChipLabel } from './FilterBarChipLabel'
import { FilterBarChipMenu } from './FilterBarChipMenu'
import {
    fieldFromFilter,
    filterValues,
    operatorLabelForFilter,
    operatorOptionsForFilter,
    propertyTypeForFilter,
    valueKindForFilter,
    valueLabelForFilter,
} from './filterBarFields'
import { FilterBarFieldSegment } from './FilterBarFieldSegment'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarOperatorRadioItems } from './FilterBarOperatorRadioItems'
import { FilterBarItem } from './filterBarTypes'
import { FilterBarUnsupportedChip } from './FilterBarUnsupportedChip'
import { FilterBarValueRows } from './FilterBarValueRows'

/** A short operator list reads at a glance, so only a longer one gets a search field. */
const OPERATOR_SEARCH_MIN_OPTIONS = 7
/** Past this many, the values stop fitting a chip, so it counts them instead. */
const MAX_VALUE_BADGES = 3

/**
 * One filter as a segmented chip: the field, the operator, the value, and a remove button. The operator and value
 * segments open menus, so a filter is edited in place.
 */
export function FilterBarChip({
    item,
    wrapType,
}: {
    item: FilterBarItem
    wrapType?: FilterLogicalOperator | null
}): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { describeProperty } = useValues(propertyDefinitionsModel)
    const { removeItem, commitItem, loadItemValues, openSqlDialog, replaceItemField } = useActions(filterBarLogic)
    const [valueQuery, setValueQuery] = useState('')
    const { filter } = item
    const field = fieldFromFilter(filter)
    if (!field) {
        return <FilterBarUnsupportedChip item={item} wrapType={wrapType} />
    }
    const propertyType = propertyTypeForFilter(filter, describeProperty)
    const operatorOptions = operatorOptionsForFilter(filter, propertyType)
    const kind = valueKindForFilter(filter, propertyType)
    const value = valueLabelForFilter(filter, cohortsById)
    const isSql = filter.type === PropertyFilterType.HogQL

    const listValues = kind === 'list' ? filterValues(filter).map(String) : []
    const fieldLabel = (
        <>
            <FilterBarCategoryIcon categoryId={field.categoryId} className="shrink-0" />
            <span className="truncate">{isSql ? 'SQL' : field.label}</span>
        </>
    )

    return (
        <ButtonGroup className="max-w-full" data-attr="filter-bar-chip">
            {isSql || field.categoryId === 'cohorts' ? (
                <FilterBarChipLabel>{fieldLabel}</FilterBarChipLabel>
            ) : (
                <FilterBarFieldSegment
                    purpose="replace-property"
                    onPick={(picked) => replaceItemField(item.id, picked)}
                >
                    {fieldLabel}
                </FilterBarFieldSegment>
            )}
            {!isSql && (
                <DropdownMenuFilterProvider autoHighlight>
                    <DropdownMenu modal={false}>
                        <DropdownMenuTrigger render={<Button variant="outline" />} data-attr="filter-bar-chip-operator">
                            {operatorLabelForFilter(filter)}
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                            header={
                                operatorOptions.length >= OPERATOR_SEARCH_MIN_OPTIONS ? (
                                    <DropdownMenuInput aria-label="Search operators" placeholder="Operator…" />
                                ) : undefined
                            }
                        >
                            <FilterBarOperatorRadioItems item={item} options={operatorOptions} />
                        </DropdownMenuContent>
                    </DropdownMenu>
                </DropdownMenuFilterProvider>
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
                                {listValues.length >= 2 && listValues.length <= MAX_VALUE_BADGES ? (
                                    listValues.map((listValue) => (
                                        <Badge key={listValue} variant="info" className="max-w-24">
                                            <span className="truncate">{listValue}</span>
                                        </Badge>
                                    ))
                                ) : (
                                    <span className="truncate">{value.text}</span>
                                )}
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
            <FilterBarChipMenu nodeId={item.id} wrapType={wrapType} />
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
