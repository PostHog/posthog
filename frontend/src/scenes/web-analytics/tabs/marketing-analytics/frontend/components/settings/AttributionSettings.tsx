import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconInfo } from '@posthog/icons'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { debounce } from 'lib/utils'

import { AttributionMode } from '~/queries/schema/schema-general'
import { teamLogic } from '~/scenes/teamLogic'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

const DEFAULT_ATTRIBUTION_WINDOW_WEEKS = 52
const DEFAULT_ATTRIBUTION_MODE = AttributionMode.LastTouch

export function AttributionSettings(): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCurrentTeam } = useActions(marketingAnalyticsSettingsLogic)
    const { currentTeamLoading } = useValues(teamLogic)

    // Get attribution settings from config with defaults
    const attribution_window_weeks =
        marketingAnalyticsConfig?.attribution_window_weeks ?? DEFAULT_ATTRIBUTION_WINDOW_WEEKS
    const attribution_mode = marketingAnalyticsConfig?.attribution_mode ?? DEFAULT_ATTRIBUTION_MODE

    // Local state for immediate UI updates
    const [localWeeks, setLocalWeeks] = useState(attribution_window_weeks)
    const [localAttributionMode, setLocalAttributionMode] = useState(attribution_mode)

    // Sync local state when store value changes
    useEffect(() => {
        setLocalWeeks(attribution_window_weeks)
    }, [attribution_window_weeks])

    useEffect(() => {
        setLocalAttributionMode(attribution_mode)
    }, [attribution_mode])

    const updateAttributionWindowWeeks = (weeks: number): void => {
        updateCurrentTeam({
            marketing_analytics_config: {
                ...marketingAnalyticsConfig,
                attribution_window_weeks: weeks,
            },
        })
    }

    const updateAttributionMode = (mode: AttributionMode): void => {
        updateCurrentTeam({
            marketing_analytics_config: {
                ...marketingAnalyticsConfig,
                attribution_mode: mode,
            },
        })
    }

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

    // Handle attribution mode change: update UI immediately, update backend
    const handleAttributionModeChange = (mode: AttributionMode): void => {
        setLocalAttributionMode(mode)
        updateAttributionMode(mode)
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
                    <label className="block text-sm font-medium mb-2 flex items-center gap-1">
                        Attribution Window
                        <Tooltip title="The attribution window determines how far back in time to look for marketing touchpoints when attributing conversions. Example: With a 4-week window, if someone converts today, we'll look back 4 weeks for any UTM campaigns they interacted with. Recommendation: Use 4-8 weeks for short sales cycles, 12+ weeks for longer consideration periods.">
                            <IconInfo className="text-muted-alt hover:text-default cursor-help" />
                        </Tooltip>
                    </label>
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
                    <label className="block text-sm font-medium mb-2 flex items-center gap-1">
                        Attribution Mode
                        <Tooltip title="Attribution mode determines which marketing touchpoint gets credit for a conversion when multiple touchpoints exist. First Touch: Credits the first marketing touchpoint in the customer journey. Best for measuring brand awareness and top-of-funnel campaigns. Last Touch: Credits the last marketing touchpoint before conversion. Best for measuring bottom-of-funnel effectiveness and direct conversion drivers.">
                            <IconInfo className="text-muted-alt hover:text-default cursor-help" />
                        </Tooltip>
                    </label>
                    <div className="max-w-md">
                        <LemonSelect
                            value={localAttributionMode}
                            onChange={handleAttributionModeChange}
                            options={attributionModeOptions}
                        />
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                        {localAttributionMode === AttributionMode.FirstTouch
                            ? 'Credit the first marketing touchpoint in the customer journey'
                            : 'Credit the last marketing touchpoint before conversion'}
                    </p>
                </div>
            </div>
        </div>
    )
}
