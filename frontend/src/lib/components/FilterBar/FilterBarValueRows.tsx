import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    DropdownMenuCheckboxItem,
    DropdownMenuItem,
    DropdownMenuList,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    MenuEmpty,
    Spinner,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyFilterType } from '~/types'

import { categoryIdForFilter } from './filterBarCategories'
import {
    filterValues,
    groupTypeIndexForCategory,
    operatorLabelForFilter,
    propertyDefinitionTypeForCategory,
    valueKindForFilter,
} from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarOperatorRadioItems } from './FilterBarOperatorRadioItems'
import { FilterBarItem } from './filterBarTypes'

const DATE_PRESETS: { label: string; value: () => string }[] = [
    { label: 'Today', value: () => dayjs().format('YYYY-MM-DD') },
    { label: 'Yesterday', value: () => dayjs().subtract(1, 'day').format('YYYY-MM-DD') },
    { label: '7 days ago', value: () => dayjs().subtract(7, 'day').format('YYYY-MM-DD') },
    { label: '30 days ago', value: () => dayjs().subtract(30, 'day').format('YYYY-MM-DD') },
    { label: 'Start of this month', value: () => dayjs().startOf('month').format('YYYY-MM-DD') },
    { label: 'Start of this year', value: () => dayjs().startOf('year').format('YYYY-MM-DD') },
]

/**
 * The value picker for one filter: an operator submenu, then the values. Lists tick several values, a number or
 * date takes one, and the menu's search field doubles as the place to type a value the list does not offer.
 */
export function FilterBarValueRows({ item, query }: { item: FilterBarItem; query: string }): JSX.Element {
    const { describeProperty, options } = useValues(propertyDefinitionsModel)
    const { allCohorts, allCohortsLoading } = useValues(cohortsModel)
    const { toggleItemValue, setItemValue, setItemCohort } = useActions(filterBarLogic)
    const { filter } = item
    const categoryId = categoryIdForFilter(filter)
    const propertyType = categoryId
        ? describeProperty(
              filter.key ?? '',
              propertyDefinitionTypeForCategory(categoryId),
              groupTypeIndexForCategory(categoryId)
          )
        : null
    const kind = valueKindForFilter(filter, propertyType)
    const selected = filterValues(filter).map(String)
    const typed = query.trim()
    const propertyOptions = filter.key ? options[filter.key] : undefined
    const loaded = (propertyOptions?.values ?? [])
        .map((value) => String(value.name ?? ''))
        .filter((value) => value !== '' && !selected.includes(value))
    const loading = propertyOptions?.status === 'loading'

    const operatorRow =
        filter.type === PropertyFilterType.HogQL ? null : (
            <>
                <DropdownMenuSeparator />
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger data-attr="filter-bar-operator-menu">
                        Operator
                        <span className="ms-auto text-muted-foreground">{operatorLabelForFilter(filter)}</span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                        <FilterBarOperatorRadioItems item={item} propertyType={propertyType} />
                    </DropdownMenuSubContent>
                </DropdownMenuSub>
            </>
        )

    const typedRow = (value: string | number, label: string): JSX.Element => (
        <DropdownMenuItem
            closeOnClick={kind !== 'list'}
            onClick={() => toggleItemValue(item.id, value, kind)}
            data-attr="filter-bar-value-typed"
        >
            <IconPlus />
            <span className="truncate">{label}</span>
        </DropdownMenuItem>
    )

    let rows: JSX.Element | JSX.Element[] | null
    switch (kind) {
        case 'none':
            rows = <MenuEmpty>This operator takes no value</MenuEmpty>
            break
        case 'boolean':
            rows = ['true', 'false'].map((value) => (
                <DropdownMenuCheckboxItem
                    key={value}
                    checked={selected.includes(value)}
                    onCheckedChange={() => toggleItemValue(item.id, value, kind)}
                    data-attr="filter-bar-value"
                >
                    {value}
                </DropdownMenuCheckboxItem>
            ))
            break
        case 'number': {
            const number = Number(typed)
            rows = (
                <>
                    {typed && Number.isFinite(number)
                        ? typedRow(number, `Use ${number}`)
                        : !typed && <MenuEmpty>Type a number</MenuEmpty>}
                    {typed && !Number.isFinite(number) && <MenuEmpty>"{typed}" is not a number</MenuEmpty>}
                    {loaded.slice(0, 10).map((value) => (
                        <DropdownMenuCheckboxItem
                            key={value}
                            checked={selected.includes(value)}
                            closeOnClick
                            onCheckedChange={() => toggleItemValue(item.id, Number(value), kind)}
                            data-attr="filter-bar-value"
                        >
                            {value}
                        </DropdownMenuCheckboxItem>
                    ))}
                </>
            )
            break
        }
        case 'date': {
            const typedIsDate = dayjs(typed, 'YYYY-MM-DD', true).isValid()
            rows = (
                <>
                    {typed && typedIsDate && typedRow(typed, `Use ${typed}`)}
                    {typed && !typedIsDate && <MenuEmpty>Type a date as YYYY-MM-DD</MenuEmpty>}
                    {DATE_PRESETS.map((preset) => {
                        const value = preset.value()
                        return (
                            <DropdownMenuCheckboxItem
                                key={preset.label}
                                checked={selected.includes(value)}
                                closeOnClick
                                onCheckedChange={() => setItemValue(item.id, value)}
                                data-attr="filter-bar-value"
                            >
                                {preset.label}
                                <span className="ms-auto text-muted-foreground">{value}</span>
                            </DropdownMenuCheckboxItem>
                        )
                    })}
                </>
            )
            break
        }
        case 'cohort': {
            const cohorts = allCohorts.results.filter(
                (cohort) =>
                    !cohort.deleted && (!typed || (cohort.name ?? '').toLowerCase().includes(typed.toLowerCase()))
            )
            rows = (
                <>
                    {cohorts.map((cohort) => (
                        <DropdownMenuCheckboxItem
                            key={cohort.id}
                            checked={filter.type === PropertyFilterType.Cohort && filter.value === cohort.id}
                            closeOnClick
                            onCheckedChange={() => setItemCohort(item.id, cohort)}
                            data-attr="filter-bar-value"
                        >
                            {cohort.name || `Cohort ${cohort.id}`}
                        </DropdownMenuCheckboxItem>
                    ))}
                    {allCohortsLoading && cohorts.length === 0 && (
                        <MenuEmpty>
                            <Spinner />
                            Loading cohorts…
                        </MenuEmpty>
                    )}
                    {!allCohortsLoading && cohorts.length === 0 && (
                        <MenuEmpty>{typed ? `No cohort matches "${typed}"` : 'No cohorts yet'}</MenuEmpty>
                    )}
                </>
            )
            break
        }
        case 'sql':
            rows = null
            break
        default:
            rows = (
                <>
                    {typed && !selected.includes(typed) && !loaded.includes(typed) && typedRow(typed, `Use "${typed}"`)}
                    {selected.map((value) => (
                        <DropdownMenuCheckboxItem
                            key={value}
                            checked
                            onCheckedChange={() => toggleItemValue(item.id, value, kind)}
                            data-attr="filter-bar-value"
                        >
                            {value}
                        </DropdownMenuCheckboxItem>
                    ))}
                    {loaded.map((value) => (
                        <DropdownMenuCheckboxItem
                            key={value}
                            checked={false}
                            onCheckedChange={() => toggleItemValue(item.id, value, kind)}
                            data-attr="filter-bar-value"
                        >
                            {value}
                        </DropdownMenuCheckboxItem>
                    ))}
                    {loading && loaded.length === 0 && (
                        <MenuEmpty>
                            <Spinner />
                            Loading values…
                        </MenuEmpty>
                    )}
                    {!loading && loaded.length === 0 && selected.length === 0 && !typed && (
                        <MenuEmpty>No values seen yet. Type one to use it.</MenuEmpty>
                    )}
                </>
            )
    }

    // The operator row comes after the list, so typing highlights the first value and Enter picks it.
    return (
        <>
            <DropdownMenuList>{rows}</DropdownMenuList>
            {operatorRow}
        </>
    )
}
