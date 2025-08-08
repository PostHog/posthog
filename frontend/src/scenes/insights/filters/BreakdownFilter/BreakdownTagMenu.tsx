import './BreakdownTagMenu.scss'

import { IconInfo, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { breakdownTagLogic } from './breakdownTagLogic'
import { GlobalBreakdownOptionsMenu } from './GlobalBreakdownOptionsMenu'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { BreakdownBin } from '~/queries/schema/schema-general'

export const BreakdownTagMenu = (): JSX.Element => {
    const {
        isHistogramable,
        isNormalizeable,
        histogramBinCount,
        normalizeBreakdownURL,
        histogramBinsUsed,
        breakdownBins,
        breakdown,
        breakdownType,
    } = useValues(breakdownTagLogic)

    const { removeBreakdown, setHistogramBinCount, setHistogramBinsUsed, setNormalizeBreakdownURL } =
        useActions(breakdownTagLogic)
    const { setBreakdownBins } = useActions(taxonomicBreakdownFilterLogic)

    const { isMultipleBreakdownsEnabled } = useValues(taxonomicBreakdownFilterLogic)

    // Local draft state to avoid triggering queries on every keystroke
    const [draftBins, setDraftBins] = useState<BreakdownBin[] | undefined>(undefined)

    // Reset drafts whenever the server/logic value changes externally
    useEffect(() => {
        setDraftBins(breakdownBins || undefined)
    }, [breakdownBins])

    const isSaveable = draftBins && JSON.stringify(draftBins) !== JSON.stringify(breakdownBins)

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
            {isHistogramable ? (
                <>
                    <LemonButton
                        onClick={() => setHistogramBinsUsed(true)}
                        active={histogramBinsUsed && !breakdownBins?.length}
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
                            onFocus={() => setHistogramBinsUsed(true)}
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
                        active={!histogramBinsUsed && !breakdownBins?.length}
                        className="mt-2"
                        fullWidth
                    >
                        Do not bin numeric values
                    </LemonButton>
                    <LemonButton
                        onClick={() => {
                            setBreakdownBins(
                                breakdown,
                                breakdownType,
                                !breakdownBins?.length ? [{ low: null, high: null }] : []
                            )
                        }}
                        active={!!breakdownBins?.length}
                        className="mt-2"
                        fullWidth
                    >
                        Custom bins
                    </LemonButton>
                    {!!breakdownBins?.length && (
                        <div className="p-2">
                            <div className="space-y-2">
                                {(draftBins || []).map((bin: BreakdownBin, index: number) => (
                                    <div key={index} className="flex items-center gap-2">
                                        <LemonInput
                                            type="number"
                                            className="w-24"
                                            value={bin.low ?? undefined}
                                            onChange={(lowNum) => {
                                                const low = lowNum !== undefined ? lowNum : null
                                                setDraftBins(
                                                    (draftBins || []).map((b: BreakdownBin, i: number) =>
                                                        i === index ? { ...b, low } : b
                                                    )
                                                )
                                            }}
                                            placeholder="Min"
                                        />
                                        <span>-</span>
                                        <LemonInput
                                            type="number"
                                            className="w-24"
                                            value={bin.high ?? undefined}
                                            onChange={(highNum) => {
                                                const high = highNum !== undefined ? highNum : null
                                                setDraftBins(
                                                    (draftBins || []).map((b: BreakdownBin, i: number) =>
                                                        i === index ? { ...b, high } : b
                                                    )
                                                )
                                            }}
                                            placeholder="Max"
                                        />
                                        <LemonButton
                                            size="small"
                                            status="danger"
                                            onClick={() => {
                                                setDraftBins(
                                                    (draftBins || []).filter(
                                                        (_: BreakdownBin, i: number) => i !== index
                                                    )
                                                )
                                            }}
                                            icon={<IconTrash />}
                                        />
                                    </div>
                                ))}
                            </div>
                            <LemonButton
                                className="mt-2"
                                fullWidth
                                onClick={() =>
                                    setDraftBins([...(draftBins || []), { low: null, high: null } as BreakdownBin])
                                }
                            >
                                Add bin
                            </LemonButton>
                            <div className="flex items-center gap-2 mt-2">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={() => setDraftBins(breakdownBins)}
                                    disabled={!isSaveable}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    onClick={() => setBreakdownBins(breakdown, breakdownType, draftBins || [])}
                                    disabled={!isSaveable}
                                >
                                    Save bins
                                </LemonButton>
                            </div>
                        </div>
                    )}
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
