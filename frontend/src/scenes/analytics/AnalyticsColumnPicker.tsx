import { useActions, useValues } from 'kea'

import { IconColumns } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AnalyticsListColumnKey } from '~/queries/schema/schema-general'

import { ANALYTICS_LIST_COLUMN_LABELS } from './AnalyticsListColumns'
import { ANALYTICS_LIST_COLUMN_KEYS, analyticsListLogic, analyticsSortedColumn } from './analyticsListLogic'

/** Picks the columns the list shows beside the title. The pick is saved on the person, so every Analytics list uses it. */
export function AnalyticsColumnPicker(): JSX.Element {
    const { pickedColumns, feedQuery, scope } = useValues(analyticsListLogic)
    const { setPickedColumns } = useActions(analyticsListLogic)
    const sorted = analyticsSortedColumn(feedQuery.orderBy)
    // My work only lists the person's own items, so it has no owner column to pick.
    const options = ANALYTICS_LIST_COLUMN_KEYS.filter((key) => scope !== 'mine' || key !== 'owner')

    const toggle = (key: AnalyticsListColumnKey, checked: boolean): void => {
        const next = checked ? [...pickedColumns, key] : pickedColumns.filter((column) => column !== key)
        setPickedColumns(ANALYTICS_LIST_COLUMN_KEYS.filter((column) => next.includes(column)))
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="outline" size="sm" aria-label="Columns" data-attr="analytics-list-columns" />}
            >
                <IconColumns />
                Columns
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Show columns</DropdownMenuLabel>
                    {options.map((key) => (
                        <DropdownMenuCheckboxItem
                            key={key}
                            checked={pickedColumns.includes(key) || key === sorted}
                            // The list sorts on this column, so it stays until the person sorts on another one.
                            disabled={key === sorted}
                            closeOnClick={false}
                            onCheckedChange={(checked) => toggle(key, checked)}
                            data-attr="analytics-list-column-option"
                        >
                            {key === sorted
                                ? `${ANALYTICS_LIST_COLUMN_LABELS[key]} (sorted)`
                                : ANALYTICS_LIST_COLUMN_LABELS[key]}
                        </DropdownMenuCheckboxItem>
                    ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
