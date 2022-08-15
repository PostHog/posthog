import React from 'react'
import { LemonButton, LemonDivider, LemonInput, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { FilterType } from '~/types'
import { breakdownTagLogic } from './breakdownTagLogic'
import { isAllCohort, isCohort, isPersonEventOrGroup } from './TaxonomicBreakdownFilter'

type BreakdownTagProps = {
    isHistogramable: boolean
    setFilters?: (filter: Partial<FilterType>) => void
    filters: FilterType
    onClose?: () => void
    breakdown: string | number
    logicKey: string
}

export function BreakdownTag({
    isHistogramable,
    setFilters,
    filters,
    onClose,
    breakdown,
    logicKey,
}: BreakdownTagProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const breakdownTagLogicInstance = breakdownTagLogic({ logicKey, setFilters, filters })

    const { binCount, useHistogram } = useValues(breakdownTagLogicInstance)
    const { setBinCount, setUseHistogram } = useActions(breakdownTagLogicInstance)

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
                {isPersonEventOrGroup(breakdown) && <PropertyKeyInfo value={breakdown} style={{}} />}
                {isAllCohort(breakdown) && <PropertyKeyInfo value={'All Users'} />}
                {isCohort(breakdown) && (
                    <PropertyKeyInfo value={cohortsById[breakdown]?.name || `Cohort ${breakdown}`} />
                )}
            </>
        </LemonTag>
    )
}
