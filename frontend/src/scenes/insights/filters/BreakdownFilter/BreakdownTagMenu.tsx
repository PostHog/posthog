import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'

import { breakdownTagLogic } from './breakdownTagLogic'
import { BreakdownFilter } from '~/queries/schema'

type BreakdownTagMenuProps = {
    filters: BreakdownFilter
}

export const BreakdownTagMenu = ({ filters }: BreakdownTagMenuProps): JSX.Element => {
    const { binCount, useHistogram, isHistogramable, isNormalizeable } = useValues(breakdownTagLogic)
    const { removeBreakdown, setBinCount, setUseHistogram, setNormalizeBreakdownURL } = useActions(breakdownTagLogic)

    return (
        <>
            {isNormalizeable && (
                <LemonSwitch
                    checked={!!filters.breakdown_normalize_url} // TODO move global values/actions to taxonomicBreakdownFilterLogic
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
            {isHistogramable && (
                <>
                    <LemonButton
                        onClick={() => {
                            setUseHistogram(true)
                        }}
                        status="stealth"
                        active={useHistogram}
                        fullWidth
                    >
                        Use{' '}
                        <LemonInput
                            min={1}
                            value={binCount}
                            onChange={(newValue) => {
                                setBinCount(newValue)
                            }}
                            fullWidth={false}
                            type="number"
                            className="histogram-bin-input"
                        />
                        bins
                    </LemonButton>
                    <LemonButton
                        onClick={() => {
                            setUseHistogram(false)
                        }}
                        status="stealth"
                        active={!useHistogram}
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
