import { useActions, useValues } from 'kea'

import { LemonButton, LemonDropdown, LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import {
    DEFAULT_POPULATION_EVENT_DAYS,
    POPULATION_EVENT_DAYS_PRESETS,
    PopulationChoice,
    autoresearchNewLogic,
    populationChosen,
    populationSummary,
} from '../autoresearchNewLogic'

export const POPULATION_FILTER_GROUP_TYPES = [
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.Cohorts,
]

export function PopulationPicker(): JSX.Element {
    const { newPipeline, populationPickerOpen } = useValues(autoresearchNewLogic)
    const { setPopulationChoice, setPopulationEvent, setPopulationPickerOpen } = useActions(autoresearchNewLogic)
    const kind = newPipeline.inference_population_kind
    const isCustom = newPipeline.template_key === null
    const populationEvent = typeof kind?.event === 'string' ? kind.event : null
    const populationDays = typeof kind?.days === 'number' ? kind.days : DEFAULT_POPULATION_EVENT_DAYS

    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-start"
            visible={populationPickerOpen}
            onVisibilityChange={setPopulationPickerOpen}
            overlay={
                <div className="flex flex-col gap-3 p-2 max-w-120">
                    {isCustom ? (
                        <>
                            <LemonRadio<PopulationChoice>
                                aria-label="Who the model predicts for"
                                value={newPipeline.population_choice ?? undefined}
                                onChange={setPopulationChoice}
                                radioPosition="top"
                                options={[
                                    {
                                        value: 'event',
                                        label: 'People who did an event',
                                        description:
                                            'Checks and trains faster, because only that event is read to find people.',
                                        'data-attr': 'autoresearch-new-population-event',
                                    },
                                    {
                                        value: 'all',
                                        label: 'All identified users',
                                        description:
                                            'Reads every event in the training lookback. On a project with a lot of events, the check can run out of time.',
                                        'data-attr': 'autoresearch-new-population-all',
                                    },
                                ]}
                            />
                            {newPipeline.population_choice === 'event' && (
                                <div className="flex flex-wrap items-center gap-2">
                                    <span>Did</span>
                                    <TaxonomicPopover
                                        type="secondary"
                                        size="small"
                                        groupType={TaxonomicFilterGroupType.Events}
                                        value={populationEvent}
                                        onChange={(picked) =>
                                            setPopulationEvent(picked ? String(picked) : null, populationDays)
                                        }
                                        placeholder="pick an event"
                                        data-attr="autoresearch-new-population-event-picker"
                                    />
                                    <span>in the last</span>
                                    <LemonSelect
                                        size="small"
                                        value={populationDays}
                                        onChange={(days) => setPopulationEvent(populationEvent, days)}
                                        options={POPULATION_EVENT_DAYS_PRESETS.map((days) => ({
                                            value: days,
                                            label: `${days} days`,
                                        }))}
                                        data-attr="autoresearch-new-population-days"
                                    />
                                </div>
                            )}
                        </>
                    ) : (
                        kind && (
                            <p className="text-sm mb-0">
                                The template limits this to {populationSummary(kind, [])}. Add filters to narrow it
                                further.
                            </p>
                        )
                    )}
                    <LemonField
                        name="inference_population"
                        label="Filters"
                        info="Narrow who the model scores each day. The model also learns from these people unless you set a separate training population in Advanced."
                    >
                        {({ value, onChange }) => (
                            <PropertyFilters
                                pageKey="autoresearch-new-inference-population"
                                propertyFilters={value ?? []}
                                onChange={(filters) => onChange(filters)}
                                taxonomicGroupTypes={POPULATION_FILTER_GROUP_TYPES}
                                buttonText="Add filter"
                            />
                        )}
                    </LemonField>
                </div>
            }
        >
            <LemonButton type="secondary" size="small" data-attr="autoresearch-new-population">
                {populationChosen(newPipeline)
                    ? populationSummary(kind, newPipeline.inference_population)
                    : 'choose people'}
            </LemonButton>
        </LemonDropdown>
    )
}
