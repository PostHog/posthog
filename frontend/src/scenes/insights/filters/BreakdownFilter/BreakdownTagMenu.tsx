import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'

import { breakdownTagLogic } from './breakdownTagLogic'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

import './BreakdownTagMenu.scss'

export const BreakdownTagMenu = (): JSX.Element => {
    const { isHistogramable, isNormalizeable } = useValues(breakdownTagLogic)
    const { removeBreakdown } = useActions(breakdownTagLogic)

    const { histogramBinCount, histogramBinsUsed, breakdownFilter } = useValues(taxonomicBreakdownFilterLogic)
    const { setHistogramBinCount, setHistogramBinsUsed, setNormalizeBreakdownURL, setBreakdownLimit } =
        useActions(taxonomicBreakdownFilterLogic)

    return (
        <>
            {isNormalizeable && (
                <LemonSwitch
                    checked={!!breakdownFilter.breakdown_normalize_url} // TODO move global values/actions to taxonomicBreakdownFilterLogic
                    fullWidth={true}
                    onChange={(checked) => setNormalizeBreakdownURL(checked)}
                    className="min-h-10 px-2 py-1 mb-2"
                    id="normalize-breakdown-url-switch"
                    label={
                        <div className="flex flex-row items-center font-normal">
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
            {!histogramBinsUsed && (
                <div className="flex items-center px-2 py-1 mb-2">
                    Show{' '}
                    <LemonInput
                        min={1}
                        size="small"
                        value={breakdownFilter?.breakdown_limit || 25}
                        onChange={(newValue) => {
                            setBreakdownLimit(newValue)
                        }}
                        fullWidth={false}
                        type="number"
                        className="histogram-bin-input"
                    />{' '}
                    values
                </div>
            )}
            {isHistogramable && (
                <>
                    <LemonButton
                        onClick={() => {
                            setHistogramBinsUsed(true)
                        }}
                        status="stealth"
                        active={histogramBinsUsed}
                        fullWidth
                    >
                        Use{' '}
                        <LemonInput
                            min={1}
                            size="small"
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
                        status="stealth"
                        active={!histogramBinsUsed}
                        className="mt-2"
                        fullWidth
                    >
                        Do not bin numeric values
                    </LemonButton>
                </>
            )}
            <LemonDivider />
            <LemonButton status="danger" onClick={removeBreakdown} fullWidth>
                Remove breakdown
            </LemonButton>
        </>
    )
}
