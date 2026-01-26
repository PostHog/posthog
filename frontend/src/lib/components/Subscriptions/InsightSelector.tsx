import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { DashboardTile } from '~/types'

import { MAX_INSIGHTS, insightSelectorLogic } from './insightSelectorLogic'

interface InsightSelectorProps {
    tiles: DashboardTile[]
    selectedInsightIds: number[]
    onChange: (ids: number[]) => void
    onDefaultsApplied?: (selectedIds: number[]) => void
}

export function InsightSelector({
    tiles,
    selectedInsightIds,
    onChange,
    onDefaultsApplied,
}: InsightSelectorProps): JSX.Element {
    const logic = insightSelectorLogic({ tiles })
    const { filteredTiles, insightTiles, showSearch, searchTerm, userHasInteracted } = useValues(logic)
    const { setSearchTerm, setUserHasInteracted } = useActions(logic)

    useEffect(() => {
        // Auto-select the first N insights for new subscriptions (when nothing is selected yet)
        if (insightTiles.length > 0 && selectedInsightIds.length === 0 && !userHasInteracted) {
            const defaultSelection = insightTiles.slice(0, MAX_INSIGHTS).map((tile) => tile.insight!.id)
            onChange(defaultSelection)
            onDefaultsApplied?.(defaultSelection)
        }
    }, [insightTiles.length, selectedInsightIds.length, userHasInteracted, insightTiles, onChange, onDefaultsApplied])

    if (insightTiles.length === 0) {
        return <div className="text-secondary text-sm">No insights found in this dashboard.</div>
    }

    const selectedCount = selectedInsightIds.length
    const atMaxLimit = selectedCount >= MAX_INSIGHTS

    const toggleInsight = (insightId: number): void => {
        setUserHasInteracted()
        if (selectedInsightIds.includes(insightId)) {
            const newIds = selectedInsightIds.filter((id) => id !== insightId)
            onChange(newIds)
        } else if (!atMaxLimit) {
            onChange([...selectedInsightIds, insightId])
        }
    }

    return (
        <div className="border rounded p-2 space-y-2">
            <div className="flex justify-between items-center text-sm">
                <span className="font-medium">
                    {selectedCount} of {MAX_INSIGHTS} insights selected
                </span>
                {selectedCount === 0 && <span className="text-warning">Select at least one insight</span>}
            </div>
            {showSearch && (
                <LemonInput
                    type="search"
                    placeholder="Search insights..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    fullWidth
                />
            )}
            <div className="border-t pt-2 space-y-1 max-h-[200px] overflow-y-auto">
                {filteredTiles.length === 0 ? (
                    <div className="text-secondary text-sm py-2">No insights match your search.</div>
                ) : (
                    filteredTiles.map((tile) => {
                        const insight = tile.insight!
                        const isChecked = selectedInsightIds.includes(insight.id)
                        const isDisabled = !isChecked && atMaxLimit
                        return (
                            <LemonCheckbox
                                key={tile.id}
                                checked={isChecked}
                                onChange={() => toggleInsight(insight.id)}
                                label={insight.name || insight.derived_name || 'Untitled insight'}
                                disabledReason={
                                    isDisabled && 'Maximum number of insights selected. Deselect one to add another.'
                                }
                            />
                        )
                    })
                )}
            </div>
            {atMaxLimit && (
                <div className="text-xs text-secondary">
                    Maximum {MAX_INSIGHTS} insights. Deselect one to add another.
                </div>
            )}
        </div>
    )
}
