import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import { CanvasSavedInsight, canvasBlockPickersLogic } from './canvasBlockPickersLogic'
import { SearchPicker } from './SearchPicker'

/** Picks one saved insight by name. The block stores its short id. */
export function InsightPicker({
    value,
    onChange,
}: {
    value: string | null
    onChange: (value: string | null) => void
}): JSX.Element {
    const { savedInsights, savedInsightsLoading } = useValues(canvasBlockPickersLogic)
    const { setInsightSearch } = useActions(canvasBlockPickersLogic)
    // Keeps the picked insight's name after a search narrows the list past it.
    const [picked, setPicked] = useState<CanvasSavedInsight>()
    const names = useMemo(
        () =>
            new Map([
                ...(picked ? [[picked.shortId, picked.name] as const] : []),
                ...savedInsights.map((insight) => [insight.shortId, insight.name] as const),
            ]),
        [savedInsights, picked]
    )
    const options = useMemo(() => savedInsights.map((insight) => insight.shortId), [savedInsights])
    const format = useCallback((shortId: string) => names.get(shortId) ?? shortId, [names])
    return (
        <SearchPicker
            value={value}
            onChange={(next) => {
                const name = next ? names.get(next) : undefined
                if (next && name) {
                    setPicked({ shortId: next, name })
                }
                onChange(next)
            }}
            options={options}
            loading={savedInsightsLoading}
            onOpen={() => setInsightSearch('')}
            placeholder="Pick a saved insight"
            searchPlaceholder="Search insights…"
            ariaLabel="Insight"
            format={format}
            onSearchChange={setInsightSearch}
        />
    )
}
