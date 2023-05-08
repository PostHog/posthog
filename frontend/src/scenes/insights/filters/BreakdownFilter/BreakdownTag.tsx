import { LemonButton, LemonDivider, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { FilterType } from '~/types'
import { breakdownTagLogic } from './breakdownTagLogic'
import { isAllCohort, isCohort, isPersonEventOrGroup } from './taxonomicBreakdownFilterUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

type BreakdownTagProps = {
    breakdown: string | number
    filters: FilterType
    setFilters?: (filter: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function BreakdownTag({ breakdown, filters, setFilters }: BreakdownTagProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)

    const { getPropertyDefinition } = useValues(propertyDefinitionsModel)

    const logicProps = { breakdown, filters, setFilters, getPropertyDefinition }
    const { binCount, useHistogram, isHistogramable, isNormalizeable } = useValues(breakdownTagLogic(logicProps))
    const { removeBreakdown, setBinCount, setUseHistogram, setNormalizeBreakdownURL } = useActions(
        breakdownTagLogic(logicProps)
    )

    return (
        <LemonTag
            className="taxonomic-breakdown-filter tag-pill"
            closable={!!setFilters && !isHistogramable && !isNormalizeable}
            onClose={removeBreakdown}
            popover={{
                overlay: isNormalizeable ? (
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
                        <LemonButton status="danger" onClick={removeBreakdown} fullWidth>
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
                        <LemonButton status="danger" onClick={removeBreakdown} fullWidth>
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
