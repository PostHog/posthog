import { useActions, useValues, useMountedLogic } from 'kea'

import { IconSort } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp, IconSwapHoriz } from 'lib/lemon-ui/icons'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { BISortDirection } from '~/queries/schema/schema-business-intelligence'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { LIMIT_OPTIONS } from 'products/business_intelligence/frontend/biEditorOptions'
import { getBIVisualizationSource } from 'products/business_intelligence/frontend/biQueryResults'
import { biSceneLogic } from 'products/business_intelligence/frontend/biSceneLogic'
import { BIChartTypes } from 'products/business_intelligence/frontend/components/BIChartTypes'

import { BIDateControls } from './BIDateControls'

export function BIToolbar(): JSX.Element {
    const editor = useMountedLogic(biEditorLogic)
    const scene = biSceneLogic({ tabId: editor.props.tabId })
    const { dataNodeKey, lastRunQuery, worksheet } = useValues(scene)
    const { runQuery, cancelQuery } = useActions(scene)
    const { responseLoading } = useValues(
        dataNodeLogic({
            key: dataNodeKey,
            query: getBIVisualizationSource(lastRunQuery ?? worksheet),
            autoLoad: !!lastRunQuery,
        })
    )
    const { autoUpdate, config, generatedQuery, chartTypesOpen, sortOptions } = useValues(biEditorLogic)
    const { resetConfig, setAutoUpdate, setLimit, setChartTypesOpen, setSort, swapRowsAndColumns } =
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
                size="xsmall"
                type="primary"
                onClick={responseLoading ? cancelQuery : runQuery}
                disabledReason={
                    !config.source
                        ? 'Select a table before running'
                        : !generatedQuery
                          ? 'Fix invalid worksheet fields before running'
                          : undefined
                }
                data-attr="bi-editor-run-query"
            >
                {responseLoading ? 'Cancel' : 'Run'}
            </LemonButton>
            <LemonButton
                icon={<IconSwapHoriz />}
                size="xsmall"
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
                size="xsmall"
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
                size="xsmall"
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
                        tooltip: 'Sorts dates from oldest to newest, or other dimensions by the highest value first.',
                    },
                    ...sortOptions.map((option) => ({ value: option.key, label: option.label })),
                ]}
                onChange={(key) => setSort(key === null ? null : { key, direction: config.sort?.direction ?? 'desc' })}
                renderButtonContent={(option) => `Sort: ${option?.label ?? 'Auto'}`}
                icon={<IconSort />}
                aria-label="Sort results by"
                size="xsmall"
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
                size="xsmall"
                type="tertiary"
                dropdownMatchSelectWidth={false}
                data-attr="bi-editor-query-limit"
            />
            <LemonDivider vertical />
            <BIDateControls />
            {config.comparisonPeriod && (
                <span className="text-xs text-secondary">Comparison window of this reference range</span>
            )}
            <LemonDivider vertical />
            <LemonButton
                size="xsmall"
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
                <LemonDropdown overlay={<BIChartTypes docked={false} />} placement="bottom-end">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        className="@3xl/bi-editor:hidden"
                        data-attr="bi-editor-show-me"
                    >
                        Chart types
                    </LemonButton>
                </LemonDropdown>
                {!chartTypesOpen ? (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        className="hidden @3xl/bi-editor:flex"
                        onClick={() => setChartTypesOpen(true)}
                        data-attr="bi-editor-show-me"
                    >
                        Chart types
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}
