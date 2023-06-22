import { BindLogic, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { FilterType, InsightType } from '~/types'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonSelect } from '@posthog/lemon-ui'
import { SamplingFilter } from 'scenes/insights/EditorFilters/SamplingFilter'
import { PREVIEW_INSIGHT_ID } from './constants'
import { Query } from '~/queries/Query/Query'

import './Experiment.scss'

export interface MetricSelectorProps {
    setPreviewInsight: (filters?: Partial<FilterType>) => void
    setFilters: (filters: Partial<FilterType>) => void
    filters: Partial<FilterType>
}

export function MetricSelector({ setPreviewInsight, filters, setFilters }: MetricSelectorProps): JSX.Element {
    // insightLogic
    const logic = insightLogic({ dashboardItemId: PREVIEW_INSIGHT_ID, syncWithUrl: false })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { query } = useValues(insightDataLogic(insightProps))

    // insightVizDataLogic
    const { isTrends, series } = useValues(insightVizDataLogic(insightProps))

    const experimentInsightType = filters.insight

    // calculated properties
    const filterSteps = series || []
    const isStepsEmpty = filterSteps.length === 0

    return (
        <>
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Insight Type</span>
                <LemonSelect
                    value={experimentInsightType}
                    onChange={(val) => {
                        val && setPreviewInsight({ insight: val })
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>

            <div>
                <SamplingFilter
                    insightProps={insightProps}
                    infoTooltipContent="Sampling on experiment goals is an Alpha feature to enable faster computation of experiment results."
                    setFilters={(payload) =>
                        setFilters({
                            ...filters,
                            ...(payload.sampling_factor
                                ? { sampling_factor: payload.sampling_factor }
                                : { sampling_factor: null }),
                        })
                    }
                    initialSamplingPercentage={filters.sampling_factor ? filters.sampling_factor * 100 : null}
                />
                <br />
            </div>

            <ActionFilter
                bordered
                filters={filters}
                setFilters={(payload) => {
                    setFilters({
                        ...filters,
                        insight: experimentInsightType,
                        ...payload,
                    })
                }}
                typeKey={`experiment-funnel-goal-${JSON.stringify(filters)}`}
                mathAvailability={isTrends ? undefined : MathAvailability.None}
                hideDeleteBtn={isTrends || filterSteps.length === 1}
                buttonCopy={isTrends ? 'Add graph series' : 'Add funnel step'}
                showSeriesIndicator={isTrends || !isStepsEmpty}
                entitiesLimit={isTrends ? 1 : undefined}
                seriesIndicatorType={isTrends ? undefined : 'numeric'}
                sortable={isTrends ? undefined : true}
                showNestedArrow={isTrends ? undefined : true}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                ]}
            />

            <div className="mt-4">
                <BindLogic logic={insightLogic} props={insightProps}>
                    <Query query={query} context={{ insightProps }} readOnly />
                </BindLogic>
            </div>
        </>
    )
}
