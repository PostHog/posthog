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
import { BIShowMe } from 'products/business_intelligence/frontend/components/BIShowMe'

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
    const { autoUpdate, config, generatedQuery, showMeOpen, sortOptions } = useValues(biEditorLogic)
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
                size="small"
                type="primary"
                onClick={responseLoading ? cancelQuery : runQuery}
                disabledReason={
                    !config.source && !config.querySnapshot
                        ? 'Select a table before running'
                        : !generatedQuery
                          ? 'Fix invalid worksheet fields before running'
                          : undefined
                }
                data-attr="bi-editor-run-query"
            >
                {responseLoading ? 'Cancel' : 'Run'}
            </LemonButton>
            {!config.querySnapshot && (
                <>
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
                        onChange={(key) =>
                            setSort(key === null ? null : { key, direction: config.sort?.direction ?? 'desc' })
                        }
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
                    <BIDateControls />
                    {config.comparisonPeriod && (
                        <span className="text-xs text-secondary">Comparison window of this reference range</span>
                    )}
                    <LemonDivider vertical />
                </>
            )}
            <LemonButton
                size="small"
                type="tertiary"
                onClick={resetConfig}
                disabledReason={!config.source && !config.querySnapshot ? 'Nothing to clear' : undefined}
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
                {!showMeOpen && !config.querySnapshot ? (
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
