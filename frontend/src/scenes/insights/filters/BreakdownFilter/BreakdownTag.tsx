import { LemonButton, LemonDivider, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { FilterType } from '~/types'
import { breakdownTagLogic } from './breakdownTagLogic'
import { isAllCohort, isCohort, isPersonEventOrGroup } from './TaxonomicBreakdownFilter'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'

type BreakdownTagProps = {
    isHistogramable: boolean
    // e.g. example.com and example.com/ should be treated as the same value
    isURLNormalizeable: boolean
    setFilters?: (filter: Partial<FilterType>, mergeFilters?: boolean) => void
    filters: FilterType
    onClose?: () => void
    breakdown: string | number
    logicKey: string
}

export function BreakdownTag({
    isHistogramable,
    isURLNormalizeable,
    setFilters,
    filters,
    onClose,
    breakdown,
    logicKey,
}: BreakdownTagProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const breakdownTagLogicInstance = breakdownTagLogic({ logicKey, setFilters, filters })

    const { binCount, useHistogram } = useValues(breakdownTagLogicInstance)
    const { setBinCount, setUseHistogram, setNormalizeBreakdownURL } = useActions(breakdownTagLogicInstance)

    return (
        <LemonTag
            className="taxonomic-breakdown-filter tag-pill"
            closable={!!setFilters && !isHistogramable && !isURLNormalizeable}
            onClose={onClose}
            style={{ textTransform: 'capitalize' }}
            popover={{
                overlay: isURLNormalizeable ? (
                    <>
                        <LemonSwitch
                            checked={!!filters.breakdown_normalize_url}
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
                                                    Strip noise (trailing slashes, question marks, and hashes) from
                                                    paths by enabling this option.
                                                </p>
                                                <p>
                                                    Without path normalization, "https://example.com",
                                                    "https://example.com/", "https://example.com/?" and
                                                    "https://example.com/#" are treated as four distinct breakdown
                                                    values. With normalization, they all count towards
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
                        <LemonDivider />
                        <LemonButton status="danger" onClick={onClose} fullWidth>
                            Remove breakdown
                        </LemonButton>
                    </>
                ) : isHistogramable ? (
                    <div>
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
                        <LemonDivider />
                        <LemonButton status="danger" onClick={onClose} fullWidth>
                            Remove breakdown
                        </LemonButton>
                    </div>
                ) : undefined,
                closeOnClickInside: false,
            }}
        >
            <>
                {isPersonEventOrGroup(breakdown) && <PropertyKeyInfo value={breakdown} />}
                {isAllCohort(breakdown) && <PropertyKeyInfo value={'All Users'} />}
                {isCohort(breakdown) && (
                    <PropertyKeyInfo value={cohortsById[breakdown]?.name || `Cohort ${breakdown}`} />
                )}
            </>
        </LemonTag>
    )
}
