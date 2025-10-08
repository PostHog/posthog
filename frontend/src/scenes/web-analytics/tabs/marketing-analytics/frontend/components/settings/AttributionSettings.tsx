import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { debounce } from 'lib/utils'

import { AttributionMode } from '~/queries/schema/schema-general'
import { teamLogic } from '~/scenes/teamLogic'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

export function AttributionSettings(): JSX.Element {
    const { attribution_window_weeks, attribution_mode } = useValues(marketingAnalyticsSettingsLogic)
    const { updateAttributionWindowWeeks, updateAttributionMode } = useActions(marketingAnalyticsSettingsLogic)
    const { currentTeamLoading } = useValues(teamLogic)

    // Local state for immediate UI updates
    const [localWeeks, setLocalWeeks] = useState(attribution_window_weeks)

    // Sync local state when store value changes (e.g., on load)
    useEffect(() => {
        setLocalWeeks(attribution_window_weeks)
    }, [attribution_window_weeks])

    // Debounce the team update to avoid excessive API calls
    const debouncedUpdateWeeks = useMemo(
        () => debounce((weeks: number) => updateAttributionWindowWeeks(weeks), 500),
        [updateAttributionWindowWeeks]
    )

    // Handle slider change: update UI immediately, debounce team update
    const handleWeeksChange = (weeks: number): void => {
        setLocalWeeks(weeks)
        debouncedUpdateWeeks(weeks)
    }

    const attributionModeOptions = [
        { value: AttributionMode.FirstTouch, label: 'First Touch' },
        { value: AttributionMode.LastTouch, label: 'Last Touch' },
    ]

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
                    Attribution Settings
                    {currentTeamLoading && <Spinner className="text-muted" />}
                </h3>
                <p className="text-muted-foreground text-sm mb-4">
                    Configure how conversions are attributed to marketing campaigns.{' '}
                    <b>Changes are saved automatically.</b>
                </p>
            </div>

            <div className="space-y-6">
                <div>
                    <label className="block text-sm font-medium mb-2">Attribution Window</label>
                    <div className="max-w-md">
                        <LemonSlider min={1} max={52} step={1} value={localWeeks} onChange={handleWeeksChange} />
                        <div className="text-sm text-muted-foreground mt-2">
                            {localWeeks} week{localWeeks !== 1 ? 's' : ''} ({localWeeks * 7} days)
                        </div>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                        How far back to look for marketing touchpoints when attributing conversions
                    </p>
                </div>

                <div>
                    <label className="block text-sm font-medium mb-2">Attribution Mode</label>
                    <div className="max-w-md">
                        <LemonSelect
                            value={attribution_mode}
                            onChange={(value) => updateAttributionMode(value)}
                            options={attributionModeOptions}
                        />
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                        {attribution_mode === AttributionMode.FirstTouch
                            ? 'Credit the first marketing touchpoint in the customer journey'
                            : 'Credit the last marketing touchpoint before conversion'}
                    </p>
                </div>
            </div>
        </div>
    )
}
