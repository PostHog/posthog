import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { groupsModel } from '~/models/groupsModel'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { EditorFilterProps, FilterType, InsightType } from '~/types'
import { alphabet } from 'lib/utils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/components/Tooltip'
import { IconCalculate } from 'lib/components/icons'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'

export function TrendsSeries({ insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const { filters, isFormulaOn, secondAxisSeriesOptions } = useValues(trendsLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const propertiesTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(filters.insight === InsightType.TRENDS ? [TaxonomicFilterGroupType.Sessions] : []),
    ]

    return (
        <>
            {filters.insight === InsightType.LIFECYCLE && (
                <div className="mb-2">
                    Showing <b>Unique users</b> who did
                </div>
            )}
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                typeKey={`trends_${InsightType.TRENDS}`}
                buttonCopy={`Add graph ${isFormulaOn ? 'variable' : 'series'}`}
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={
                    filters.insight === InsightType.LIFECYCLE ||
                    (filters.display && SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display) && !isFormulaOn)
                        ? 1
                        : alphabet.length
                }
                mathAvailability={
                    filters.insight === InsightType.LIFECYCLE
                        ? MathAvailability.None
                        : filters.insight === InsightType.STICKINESS
                        ? MathAvailability.ActorsOnly
                        : MathAvailability.All
                }
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
            />
            <div className={'flex justify-end'}>
                <LemonLabel>
                    second axis:
                    <LemonSelect
                        value={null}
                        options={secondAxisSeriesOptions}
                        onChange={(choice) => setFilters({ second_axis_series: choice }, true)}
                    />
                </LemonLabel>
            </div>
        </>
    )
}

export function TrendsSeriesLabel({ insightProps }: EditorFilterProps): JSX.Element {
    const { filters, localFilters, isFormulaOn } = useValues(trendsLogic(insightProps))
    const { setIsFormulaOn } = useActions(trendsLogic(insightProps))

    const formulaModeButtonDisabled: boolean =
        isFormulaOn &&
        !!filters.display &&
        SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display) &&
        localFilters.length > 1

    return (
        <div className="flex items-center justify-between w-full">
            <span>{isFormulaOn ? 'Variables' : 'Series'}</span>
            <Tooltip
                title={
                    formulaModeButtonDisabled
                        ? 'This chart type does not support multiple series, so in order to disable formula mode, remove variables or switch to a different chart type.'
                        : 'Make your own formula the output of the insight with formula mode. Use graph series as variables.'
                }
            >
                {/** The negative margin negates the button's effect on label sizing. */}
                <div style={{ margin: '-0.25rem 0' }}>
                    <LemonButton
                        size="small"
                        onClick={() => setIsFormulaOn(!isFormulaOn)}
                        disabled={formulaModeButtonDisabled}
                        icon={<IconCalculate />}
                        id="trends-formula-switch"
                    >
                        {isFormulaOn ? 'Disable' : 'Enable'} formula mode
                    </LemonButton>
                </div>
            </Tooltip>
        </div>
    )
}
