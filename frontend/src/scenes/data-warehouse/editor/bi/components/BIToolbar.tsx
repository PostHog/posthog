import { useActions, useValues } from 'kea'

import { IconSort } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp, IconSwapHoriz } from 'lib/lemon-ui/icons'

import { biEditorLogic } from '../biEditorLogic'
import { LIMIT_OPTIONS } from '../biEditorOptions'
import { BISortDirection } from '../biEditorTypes'
import { BIShowMe } from './BIShowMe'

export function BIToolbar(): JSX.Element {
    const { autoUpdate, config, showMeOpen, sortOptions } = useValues(biEditorLogic)
    const { resetConfig, setAutoUpdate, setLimit, setShowMeOpen, setSort, swapRowsAndColumns } =
        useActions(biEditorLogic)

    // Quick sort follows the chosen sort field, or the first measure like desktop BI tools do
    const quickSortKey = config.sort?.key ?? sortOptions.find((option) => option.key.startsWith('values:'))?.key ?? null
    const quickSort = (direction: BISortDirection): void => {
        if (quickSortKey) {
            setSort({ key: quickSortKey, direction })
        }
    }
    const noSortReason = quickSortKey ? undefined : 'Add a field to rows or columns first'

    return (
        <div className="flex flex-wrap items-center gap-1 border-b px-2 py-1">
            <LemonButton
                icon={<IconSwapHoriz />}
                size="small"
                type="tertiary"
                tooltip="Swap rows and columns"
                aria-label="Swap rows and columns"
                disabledReason={
                    config.rows.length === 0 && config.columns.length === 0 ? 'No fields to swap' : undefined
                }
                onClick={swapRowsAndColumns}
                data-attr="bi-editor-swap"
            />
            <LemonButton
                icon={<IconArrowUp />}
                size="small"
                type="tertiary"
                active={config.sort?.direction === 'asc'}
                tooltip="Sort ascending"
                aria-label="Sort ascending"
                disabledReason={noSortReason}
                onClick={() => quickSort('asc')}
                data-attr="bi-editor-sort-ascending"
            />
            <LemonButton
                icon={<IconArrowDown />}
                size="small"
                type="tertiary"
                active={config.sort?.direction === 'desc'}
                tooltip="Sort descending"
                aria-label="Sort descending"
                disabledReason={noSortReason}
                onClick={() => quickSort('desc')}
                data-attr="bi-editor-sort-descending"
            />
            <LemonSelect
                value={config.sort?.key ?? null}
                options={[
                    {
                        value: null,
                        label: 'Auto',
                        tooltip:
                            'Sorts by the newest date or the highest value first, so the top rows stay within the limit.',
                    },
                    ...sortOptions.map((option) => ({ value: option.key, label: option.label })),
                ]}
                onChange={(key) => setSort(key === null ? null : { key, direction: config.sort?.direction ?? 'desc' })}
                renderButtonContent={(option) => `Sort: ${option?.label ?? 'Auto'}`}
                icon={<IconSort />}
                aria-label="Sort results by"
                size="small"
                type="tertiary"
                dropdownMatchSelectWidth={false}
                disabledReason={sortOptions.length === 0 ? 'Add a field to rows or columns first' : undefined}
                data-attr="bi-editor-sort"
            />
            <LemonSelect
                value={config.limit}
                options={LIMIT_OPTIONS}
                onChange={setLimit}
                renderButtonContent={(option) => `Limit: ${option?.label ?? config.limit}`}
                aria-label="Query row limit"
                size="small"
                type="tertiary"
                dropdownMatchSelectWidth={false}
                data-attr="bi-editor-query-limit"
            />
            <LemonDivider vertical />
            <LemonButton
                size="small"
                type="tertiary"
                onClick={resetConfig}
                disabledReason={!config.source ? 'Nothing to clear' : undefined}
                data-attr="bi-editor-clear"
            >
                Clear sheet
            </LemonButton>
            <div className="ml-auto flex items-center gap-2">
                <LemonSwitch
                    checked={autoUpdate}
                    onChange={setAutoUpdate}
                    label="Auto-update"
                    size="small"
                    tooltip="Run the query after every change"
                    data-attr="bi-editor-auto-update"
                />
                {/* Narrow sheets have no room to dock the chart picker, so it opens as a dropdown */}
                <LemonDropdown overlay={<BIShowMe docked={false} />} placement="bottom-end">
                    <LemonButton
                        size="small"
                        type="secondary"
                        className="@3xl/bi-editor:hidden"
                        data-attr="bi-editor-show-me"
                    >
                        Show me
                    </LemonButton>
                </LemonDropdown>
                {!showMeOpen ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        className="hidden @3xl/bi-editor:flex"
                        onClick={() => setShowMeOpen(true)}
                        data-attr="bi-editor-show-me"
                    >
                        Show me
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}
