import './BreakdownTagMenu.scss'

import { useActions, useValues } from 'kea'

import { IconGear, IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { GlobalBreakdownOptionsMenu } from './GlobalBreakdownOptionsMenu'
import { breakdownTagLogic } from './breakdownTagLogic'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export const BreakdownTagMenu = (): JSX.Element => {
    const {
        isHistogramable,
        isNormalizeable,
        histogramBinCount,
        normalizeBreakdownURL,
        histogramBinsUsed,
        pathCleaningEnabled,
    } = useValues(breakdownTagLogic)

    const {
        removeBreakdown,
        setHistogramBinCount,
        setHistogramBinsUsed,
        setNormalizeBreakdownURL,
        setPathCleaningEnabled,
    } = useActions(breakdownTagLogic)

    const { isMultipleBreakdownsEnabled } = useValues(taxonomicBreakdownFilterLogic)

    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const hasPathCleaningFilters = (currentTeam?.path_cleaning_filters || []).length > 0
    const isPathCleaningAvailable = isNormalizeable && hasAdvancedPaths && hasPathCleaningFilters

    return (
        <>
            {isNormalizeable && (
                <LemonSwitch
                    checked={normalizeBreakdownURL} // TODO move global values/actions to taxonomicBreakdownFilterLogic
                    fullWidth={true}
                    onChange={(checked) => setNormalizeBreakdownURL(checked)}
                    className="min-h-10 px-2"
                    id="normalize-breakdown-url-switch"
                    label={
                        <div className="flex flex-row items-center">
                            Normalize paths
                            <Tooltip
                                title={
                                    <>
                                        <p>
                                            Strip noise (trailing slashes, question marks, and hashes) from paths by
                                            enabling this option.
                                        </p>
                                        <p>
                                            Without path normalization, "https://example.com", "https://example.com/",
                                            "https://example.com/?" and "https://example.com/#" are treated as four
                                            distinct breakdown values. With normalization, they all count towards
                                            "https://example.com".
                                        </p>
                                    </>
                                }
                            >
                                <IconInfo className="text-xl text-secondary ml-1 shrink-0" />
                            </Tooltip>
                        </div>
                    }
                />
            )}
            {isPathCleaningAvailable && (
                <LemonSwitch
                    checked={pathCleaningEnabled}
                    fullWidth={true}
                    onChange={(checked) => setPathCleaningEnabled(checked)}
                    className="min-h-10 px-2"
                    id="path-cleaning-switch"
                    label={
                        <div className="flex flex-row items-center">
                            Path cleaning
                            <Tooltip
                                title={
                                    <>
                                        <p>
                                            Apply your team's path cleaning rules to standardize URLs by removing
                                            unnecessary parameters and fragments.
                                        </p>
                                        <LemonButton
                                            icon={<IconGear />}
                                            type="primary"
                                            size="small"
                                            to={urls.settings('project-product-analytics', 'path-cleaning')}
                                            targetBlank
                                            className="w-full mt-2"
                                        >
                                            Edit path cleaning settings
                                        </LemonButton>
                                    </>
                                }
                            >
                                <IconInfo className="text-xl text-secondary ml-1 shrink-0" />
                            </Tooltip>
                        </div>
                    }
                />
            )}
            {isHistogramable ? (
                <>
                    <LemonButton
                        onClick={() => {
                            setHistogramBinsUsed(true)
                        }}
                        active={histogramBinsUsed}
                        fullWidth
                    >
                        Use{' '}
                        <LemonInput
                            min={1}
                            value={histogramBinCount}
                            onChange={(newValue) => {
                                if (typeof newValue === 'number') {
                                    setHistogramBinCount(newValue)
                                }
                            }}
                            fullWidth={false}
                            type="number"
                            className="histogram-bin-input"
                        />
                        bins
                    </LemonButton>
                    <LemonButton
                        onClick={() => {
                            setHistogramBinsUsed(false)
                        }}
                        active={!histogramBinsUsed}
                        className="mt-2"
                        fullWidth
                    >
                        Do not bin numeric values
                    </LemonButton>
                </>
            ) : (
                !isMultipleBreakdownsEnabled && <GlobalBreakdownOptionsMenu />
            )}
            <LemonDivider />
            <LemonButton status="danger" onClick={removeBreakdown} fullWidth>
                Remove breakdown
            </LemonButton>
        </>
    )
}
