import { LemonButton, LemonDivider, LemonInput, LemonTag } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import React, { useState } from 'react'
import { cohortsModel } from '~/models/cohortsModel'
import { FilterType } from '~/types'
import { isAllCohort, isCohort, isPersonEventOrGroup } from './TaxonomicBreakdownFilter'

type BreakdownTagProps = {
    isHistogramable: boolean
    setFilters?: (filter: Partial<FilterType>) => void
    filters: FilterType
    onClose?: () => void
    breakdown: string | number
}

export function BreakdownTag({
    isHistogramable,
    setFilters,
    filters,
    onClose,
    breakdown,
}: BreakdownTagProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)

    const [histogramBinCount, setHistogramBinCount] = useState(filters.breakdown_histogram_bin_count || 10)

    return (
        <LemonTag
            className="taxonomic-breakdown-filter tag-pill"
            closable={!!setFilters && !isHistogramable}
            onClose={onClose}
            style={{ textTransform: 'capitalize' }}
            popup={{
                overlay: isHistogramable ? (
                    <div>
                        <LemonButton
                            onClick={() =>
                                setFilters && setFilters({ breakdown_histogram_bin_count: histogramBinCount })
                            }
                            type={filters.breakdown_histogram_bin_count ? 'highlighted' : 'stealth'}
                            fullWidth
                        >
                            Use{' '}
                            <LemonInput
                                min={1}
                                value={histogramBinCount}
                                onChange={setHistogramBinCount}
                                fullWidth={false}
                                type="number"
                                className="histogram-bin-input"
                            />
                            bins
                        </LemonButton>
                        <LemonButton
                            onClick={() => setFilters && setFilters({ breakdown_histogram_bin_count: undefined })}
                            type={filters.breakdown_histogram_bin_count === undefined ? 'highlighted' : 'stealth'}
                            className="mt-05"
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
                onClickOutside: () => {
                    setFilters && setFilters({ breakdown_histogram_bin_count: histogramBinCount })
                },
                closeOnClickInside: false,
            }}
        >
            <>
                {isPersonEventOrGroup(breakdown) && <PropertyKeyInfo value={breakdown} style={{}} />}
                {isAllCohort(breakdown) && <PropertyKeyInfo value={'All Users'} />}
                {isCohort(breakdown) && (
                    <PropertyKeyInfo value={cohortsById[breakdown]?.name || `Cohort ${breakdown}`} />
                )}
            </>
        </LemonTag>
    )
}
