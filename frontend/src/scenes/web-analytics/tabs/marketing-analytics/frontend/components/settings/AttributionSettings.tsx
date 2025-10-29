import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { debounce } from 'lib/utils'

import { AttributionMode } from '~/queries/schema/schema-general'
import { teamLogic } from '~/scenes/teamLogic'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    ATTRIBUTION_WINDOW_OPTIONS,
    DEFAULT_ATTRIBUTION_MODE,
    DEFAULT_ATTRIBUTION_WINDOW_DAYS,
    MAX_ATTRIBUTION_WINDOW_DAYS,
    MIN_ATTRIBUTION_WINDOW_DAYS,
} from '../../logic/utils'

const ATTRIBUTION_MODE_OPTIONS = [
    { value: AttributionMode.FirstTouch, label: 'First Touch' },
    { value: AttributionMode.LastTouch, label: 'Last Touch' },
]

export function AttributionSettings(): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCurrentTeam } = useActions(marketingAnalyticsSettingsLogic)
    const { currentTeamLoading } = useValues(teamLogic)

    // Get attribution settings from config with defaults
    const attribution_window_days = marketingAnalyticsConfig?.attribution_window_days ?? DEFAULT_ATTRIBUTION_WINDOW_DAYS
    const attribution_mode = marketingAnalyticsConfig?.attribution_mode ?? DEFAULT_ATTRIBUTION_MODE

    // Local state for immediate UI updates
    const [localDays, setLocalDays] = useState(attribution_window_days)
    const [isCustomValue, setIsCustomValue] = useState(
        !ATTRIBUTION_WINDOW_OPTIONS.some((option) => option.value === localDays)
    )
    const [localAttributionMode, setLocalAttributionMode] = useState(attribution_mode)

    // Sync local state when store value changes
    useEffect(() => {
        setLocalDays(attribution_window_days)
    }, [attribution_window_days, setIsCustomValue, setLocalDays])

    useEffect(() => {
        setIsCustomValue(!ATTRIBUTION_WINDOW_OPTIONS.some((option) => option.value === localDays))
    }, [localDays])

    const hasError = !(localDays >= MIN_ATTRIBUTION_WINDOW_DAYS && localDays <= MAX_ATTRIBUTION_WINDOW_DAYS)

    useEffect(() => {
        setLocalAttributionMode(attribution_mode)
    }, [attribution_mode])

    const updateAttributionWindowDays = useCallback(
        (days: number): void => {
            updateCurrentTeam({
                marketing_analytics_config: {
                    ...marketingAnalyticsConfig,
                    attribution_window_days: days,
                },
            })
        },
        [updateCurrentTeam, marketingAnalyticsConfig]
    )

    const updateAttributionMode = useCallback(
        (mode: AttributionMode): void => {
            updateCurrentTeam({
                marketing_analytics_config: {
                    ...marketingAnalyticsConfig,
                    attribution_mode: mode,
                },
            })
        },
        [updateCurrentTeam, marketingAnalyticsConfig]
    )

    // Debounce the team update to avoid excessive API calls
    const debouncedUpdateDays = useMemo(
        () => debounce((days: number) => updateAttributionWindowDays(days), 500),
        [updateAttributionWindowDays]
    )

    // Handle dropdown change: update UI immediately, debounce team update
    const handleDaysChange = useCallback(
        (days: number | string): void => {
            if (days === 'custom') {
                setIsCustomValue(true)
                return
            }
            setIsCustomValue(false)
            const numericDays = typeof days === 'string' ? parseInt(days, 10) : days
            setLocalDays(numericDays)
            debouncedUpdateDays(numericDays)
        },
        [debouncedUpdateDays]
    )

    // Handle attribution mode change: update UI immediately, update backend
    const handleAttributionModeChange = useCallback(
        (mode: AttributionMode): void => {
            setLocalAttributionMode(mode)
            updateAttributionMode(mode)
        },
        [updateAttributionMode]
    )

    const handleCustomInputChange = useCallback((value: number | undefined): void => {
        if (value !== undefined) {
            setLocalDays(value)
        }
    }, [])

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent): void => {
            if (e.key === 'Enter' && !hasError) {
                debouncedUpdateDays(localDays)
            }
        },
        [hasError, localDays, debouncedUpdateDays]
    )

    const saveCustomInput = useCallback((): void => {
        if (!hasError && localDays !== attribution_window_days) {
            debouncedUpdateDays(localDays)
        }
    }, [hasError, localDays, attribution_window_days, debouncedUpdateDays])

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
                    Attribution Settings
                    {currentTeamLoading && <Spinner className="text-muted" />}
                </h3>
                <p className="text-muted-foreground text-sm mb-4">
                    Configure how conversions are attributed to marketing campaigns.
                </p>
            </div>

            <div className="space-y-6">
                <div>
                    <label className="text-sm font-medium mb-2 flex items-center gap-1">
                        Attribution Window
                        <Tooltip title="The attribution window determines how far back in time to look for marketing touchpoints when attributing conversions. Example: With a 30-day window, if someone converts today, we'll look back 30 days for any UTM campaigns they interacted with. Recommendation: Use 30-60 days for short sales cycles, 90+ days for longer consideration periods.">
                            <IconInfo className="text-muted-alt hover:text-default cursor-help" />
                        </Tooltip>
                    </label>
                    <div className="max-w-md flex items-center gap-2">
                        <LemonSelect
                            value={isCustomValue ? 'custom' : localDays}
                            onChange={handleDaysChange}
                            options={ATTRIBUTION_WINDOW_OPTIONS}
                            data-attr="attribution-window-select"
                            className="w-50"
                        />
                        <LemonInput
                            type="number"
                            value={localDays}
                            onChange={handleCustomInputChange}
                            onKeyDown={handleKeyDown}
                            placeholder={`${MIN_ATTRIBUTION_WINDOW_DAYS}-${MAX_ATTRIBUTION_WINDOW_DAYS}`}
                            min={MIN_ATTRIBUTION_WINDOW_DAYS}
                            max={MAX_ATTRIBUTION_WINDOW_DAYS}
                            className="w-32"
                            status={hasError ? 'danger' : undefined}
                            data-attr="attribution-window-custom-input"
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={saveCustomInput}
                            disabledReason={
                                hasError
                                    ? `Please enter a valid value between ${MIN_ATTRIBUTION_WINDOW_DAYS} and ${MAX_ATTRIBUTION_WINDOW_DAYS} days`
                                    : localDays === attribution_window_days
                                      ? 'No changes to save'
                                      : undefined
                            }
                            data-attr="attribution-window-save-button"
                        >
                            Save
                        </LemonButton>
                    </div>
                    <p className={`text-xs text-muted-foreground mt-1 ${hasError ? 'text-danger' : ''}`}>
                        {hasError
                            ? `Please enter a value between ${MIN_ATTRIBUTION_WINDOW_DAYS} and ${MAX_ATTRIBUTION_WINDOW_DAYS} days`
                            : 'How far back to look for marketing touchpoints when attributing conversions'}
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
                        <div className="flex items-center gap-1 bg-border rounded p-1">
                            {ATTRIBUTION_MODE_OPTIONS.map((option) => (
                                <LemonButton
                                    key={option.value}
                                    type={localAttributionMode === option.value ? 'primary' : 'tertiary'}
                                    size="small"
                                    onClick={() => handleAttributionModeChange(option.value)}
                                    data-attr={`attribution-mode-${option.value.toLowerCase().replace('_', '-')}`}
                                    className="flex-1"
                                >
                                    {option.label}
                                </LemonButton>
                            ))}
                        </div>
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
