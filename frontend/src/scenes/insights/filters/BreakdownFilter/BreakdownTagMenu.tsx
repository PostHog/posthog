import './BreakdownTagMenu.scss'

import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconInfo } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { breakdownTagLogic } from './breakdownTagLogic'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export const BreakdownTagMenu = (): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { isHistogramable, isNormalizeable } = useValues(breakdownTagLogic)
    const { removeBreakdown } = useActions(breakdownTagLogic)
    const { breakdownFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateBreakdownFilter } = useActions(insightVizDataLogic(insightProps))

    const { histogramBinCount, breakdownLimit, histogramBinsUsed } = useValues(taxonomicBreakdownFilterLogic)
    const { setHistogramBinCount, setBreakdownLimit, setHistogramBinsUsed, setNormalizeBreakdownURL } =
        useActions(taxonomicBreakdownFilterLogic)

    return (
        <>
            {isNormalizeable && (
                <LemonSwitch
                    checked={!!breakdownFilter?.breakdown_normalize_url} // TODO move global values/actions to taxonomicBreakdownFilterLogic
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
                                <IconInfo className="text-xl text-muted-alt ml-1 shrink-0" />
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
                                setHistogramBinCount(newValue)
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
                <>
                    <LemonSwitch
                        fullWidth
                        className="min-h-10 px-2"
                        checked={!breakdownFilter?.breakdown_hide_other_aggregation}
                        onChange={() =>
                            updateBreakdownFilter({
                                ...breakdownFilter,
                                breakdown_hide_other_aggregation: !breakdownFilter?.breakdown_hide_other_aggregation,
                            })
                        }
                        label={
                            <div className="flex gap-1">
                                <span>Group remaining values under "Other"</span>
                                <Tooltip
                                    title={
                                        <>
                                            If you have over {breakdownFilter?.breakdown_limit ?? 25} breakdown options,
                                            the smallest ones are aggregated under the label "Other". Use this toggle to
                                            show/hide the "Other" option.
                                        </>
                                    }
                                >
                                    <IconInfo className="text-muted text-xl shrink-0" />
                                </Tooltip>
                            </div>
                        }
                    />
                    <div>
                        <LemonButton
                            onClick={() => {
                                updateBreakdownFilter({ breakdown_limit: breakdownLimit })
                            }}
                            active={histogramBinsUsed}
                            fullWidth
                        >
                            Breakdown limit:{' '}
                            <LemonInput
                                min={1}
                                value={breakdownLimit}
                                onChange={(newValue) => {
                                    setBreakdownLimit(newValue ?? 25)
                                }}
                                fullWidth={false}
                                className="w-20 ml-2"
                                type="number"
                            />
                        </LemonButton>
                    </div>
                </>
            )}
            <LemonDivider />
            <LemonButton status="danger" onClick={removeBreakdown} fullWidth>
                Remove breakdown
            </LemonButton>
        </>
    )
}
