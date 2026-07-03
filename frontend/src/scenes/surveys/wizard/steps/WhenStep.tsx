import { useActions, useValues } from 'kea'

import { IconInfo, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSegmentedButton, LemonSnack } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { AddEventButton } from 'scenes/surveys/AddEventButton'
import { doesSurveyRepeatOnEveryEvent } from 'scenes/surveys/utils'

import {
    AnyPropertyFilter,
    SurveyAppearance,
    SurveyDisplayConditions,
    SurveyEventsWithProperties,
    SurveySchedule,
} from '~/types'

import {
    SUPPORTED_OPERATORS,
    convertArrayToPropertyFilters,
    convertPropertyFiltersToArray,
    getEventPropertyFilterCount,
    useExcludedObjectProperties,
} from '../../SurveyEventTrigger'
import { surveyLogic } from '../../surveyLogic'
import { surveyWizardLogic } from '../surveyWizardLogic'
import { WizardPanel, WizardSection, WizardStepLayout } from '../WizardLayout'

const DEFAULT_ITERATION_COUNT = 10
const MIN_ITERATION_COUNT = 2
const MAX_ITERATION_COUNT = 500

const FREQUENCY_OPTIONS: { value: string; days: number | undefined; label: string }[] = [
    { value: 'once', days: undefined, label: 'Once ever' },
    { value: 'yearly', days: 365, label: 'Every year' },
    { value: 'quarterly', days: 90, label: 'Every 3 months' },
    { value: 'monthly', days: 30, label: 'Every month' },
]

export function WhenStep(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const { recommendedFrequency } = useValues(surveyWizardLogic({ id: survey.id || 'new' }))

    const conditions: Partial<SurveyDisplayConditions> = survey.conditions || {}
    const appearance: Partial<SurveyAppearance> = survey.appearance || {}
    const triggerEvents = conditions.events?.values || []
    // Check if events object exists (even if empty) to determine mode
    const triggerMode = conditions.events !== null && conditions.events !== undefined ? 'event' : 'pageview'
    const repeatedActivation = conditions.events?.repeatedActivation ?? false
    // Repeated event activation makes the SDK re-show the survey on every trigger-event capture,
    // bypassing the schedule — so render the schedule as not applicable, the same treatment as
    // SurveyRepeatSchedule in the full editor (the explanation is deliberately not shared with it:
    // the contexts differ too much). The stored schedule/iteration fields are left untouched so
    // unchecking the box restores the previous cadence.
    const repeatsOnEveryEvent = doesSurveyRepeatOnEveryEvent(survey)
    const delaySeconds = appearance.surveyPopupDelaySeconds ?? 0
    const excludedObjectProperties = useExcludedObjectProperties()
    // Derive frequency strictly from the iteration model — the universal wait-period is a separate
    // across-surveys gate and must not influence which cadence is highlighted. Default to 'once' so
    // an unconfigured survey doesn't silently imply a recurring cadence.
    const frequency =
        survey.schedule === SurveySchedule.Once
            ? 'once'
            : (FREQUENCY_OPTIONS.find((opt) => opt.days === survey.iteration_frequency_days)?.value ?? 'once')
    const iterationCount = survey.iteration_count ?? DEFAULT_ITERATION_COUNT
    const seenSurveyWaitPeriodInDays = conditions.seenSurveyWaitPeriodInDays ?? null

    const setTriggerMode = (mode: 'pageview' | 'event'): void => {
        if (mode === 'pageview') {
            setSurveyValue('conditions', { ...conditions, events: null })
        } else {
            // Initialize empty events structure to switch to event mode
            setSurveyValue('conditions', { ...conditions, events: { values: [], repeatedActivation: false } })
        }
    }

    const setDelaySeconds = (seconds: number): void => {
        setSurveyValue('appearance', { ...appearance, surveyPopupDelaySeconds: seconds })
    }

    const setFrequency = (value: string): void => {
        const option = FREQUENCY_OPTIONS.find((opt) => opt.value === value)
        if (value === 'once') {
            setSurveyValue('schedule', SurveySchedule.Once)
            setSurveyValue('iteration_count', 0)
            setSurveyValue('iteration_frequency_days', 0)
            return
        }
        setSurveyValue('schedule', SurveySchedule.Recurring)
        setSurveyValue(
            'iteration_count',
            survey.iteration_count && survey.iteration_count >= MIN_ITERATION_COUNT
                ? survey.iteration_count
                : DEFAULT_ITERATION_COUNT
        )
        setSurveyValue('iteration_frequency_days', option?.days)
    }

    const setIterationCount = (value: number | undefined): void => {
        // Don't clamp to min on every keystroke — typing "10" briefly passes through 1, and aggressive
        // clamping prevents the second digit from being appended. The blur handler enforces the floor.
        if (value === undefined) {
            return
        }
        setSurveyValue('iteration_count', Math.min(value, MAX_ITERATION_COUNT))
    }

    const commitIterationCount = (): void => {
        if (!survey.iteration_count || survey.iteration_count < MIN_ITERATION_COUNT) {
            setSurveyValue('iteration_count', MIN_ITERATION_COUNT)
        }
    }

    // Reactive gate: typing a positive number turns the wait-period switch on; clearing or
    // entering 0 turns it off. The switch itself just provides a quick way to seed/clear the value.
    const setSeenSurveyWaitPeriod = (value: number | null | undefined): void => {
        setSurveyValue('conditions', {
            ...conditions,
            seenSurveyWaitPeriodInDays: value && value > 0 ? value : null,
        })
    }

    const setResponsesLimit = (value: number | null | undefined): void => {
        setSurveyValue('responses_limit', value && value > 0 ? value : null)
    }

    const setRepeatedActivation = (enabled: boolean): void => {
        setSurveyValue('conditions', {
            ...conditions,
            events: { ...conditions.events, values: conditions.events?.values || [], repeatedActivation: enabled },
        })
    }

    const addTriggerEvent = (eventName: string): void => {
        const currentEvents = conditions.events?.values || []
        if (!currentEvents.some((e) => e.name === eventName)) {
            setSurveyValue('conditions', {
                ...conditions,
                events: {
                    ...conditions.events,
                    values: [...currentEvents, { name: eventName }],
                },
            })
        }
    }

    const removeTriggerEvent = (eventName: string): void => {
        const currentEvents = conditions.events?.values || []
        const newEvents = currentEvents.filter((e) => e.name !== eventName)
        setSurveyValue('conditions', {
            ...conditions,
            events: newEvents.length > 0 ? { ...conditions.events, values: newEvents } : null,
        })
    }

    const updateTriggerEvent = (eventName: string, updatedEvent: SurveyEventsWithProperties): void => {
        const currentEvents = conditions.events?.values || []
        const newEvents = currentEvents.map((event) => (event.name === eventName ? updatedEvent : event))
        setSurveyValue('conditions', {
            ...conditions,
            events: {
                ...conditions.events,
                values: newEvents,
            },
        })
    }

    const updateTriggerEventFilters = (event: SurveyEventsWithProperties, filters: AnyPropertyFilter[]): void => {
        updateTriggerEvent(event.name, {
            ...event,
            propertyFilters: convertArrayToPropertyFilters(filters),
        })
    }

    return (
        <WizardStepLayout>
            <WizardSection
                title="When should this appear?"
                description="Choose when to show this survey to your users"
                descriptionClassName="text-sm"
            >
                <LemonRadio
                    value={triggerMode}
                    onChange={setTriggerMode}
                    options={[
                        {
                            value: 'pageview',
                            label: 'On page load',
                            description: 'Shows when the user visits the page',
                        },
                        {
                            value: 'event',
                            label: 'When an event is captured',
                            description: 'Trigger the survey after specific events occur',
                        },
                    ]}
                />

                {triggerMode === 'event' && (
                    <div className="ml-6 space-y-2.5 mt-2">
                        {triggerEvents.length > 0 && (
                            <div className="space-y-2.5">
                                <div className="text-xs text-muted">
                                    Each event can be narrowed with optional property filters right below it.
                                </div>
                                {triggerEvents.map((event) => {
                                    const propertyFilterCount = getEventPropertyFilterCount(event.propertyFilters)

                                    return (
                                        <WizardPanel key={event.name} className="bg-bg-light">
                                            <div className="flex items-start justify-between gap-3 mb-3">
                                                <div className="space-y-1">
                                                    <div className="flex flex-wrap items-center gap-2">
                                                        <code className="text-sm font-mono">{event.name}</code>
                                                        <span className="text-xs text-muted bg-border px-1.5 py-0.5 rounded">
                                                            {propertyFilterCount > 0
                                                                ? `${propertyFilterCount} filter${propertyFilterCount !== 1 ? 's' : ''}`
                                                                : 'No filters yet'}
                                                        </span>
                                                    </div>
                                                    <div className="text-xs text-muted">
                                                        Show the survey only when this event matches the properties
                                                        below.
                                                    </div>
                                                </div>
                                                <LemonButton
                                                    size="xsmall"
                                                    icon={<IconX />}
                                                    onClick={() => removeTriggerEvent(event.name)}
                                                    type="tertiary"
                                                />
                                            </div>
                                            <PropertyFilters
                                                propertyFilters={convertPropertyFiltersToArray(event.propertyFilters)}
                                                onChange={(filters: AnyPropertyFilter[]) =>
                                                    updateTriggerEventFilters(event, filters)
                                                }
                                                pageKey={`survey-wizard-event-${event.name}`}
                                                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                                excludedProperties={excludedObjectProperties}
                                                eventNames={[event.name]}
                                                buttonText="Add property filter"
                                                buttonSize="small"
                                                operatorAllowlist={SUPPORTED_OPERATORS}
                                            />
                                            <div className="text-xs text-muted mt-2">
                                                Only primitive types are supported here. Array and object properties are
                                                excluded.
                                            </div>
                                        </WizardPanel>
                                    )
                                })}
                            </div>
                        )}
                        <AddEventButton onEventSelect={addTriggerEvent} addButtonText="Add event" />
                        <div className="pt-1">
                            <LemonCheckbox
                                checked={repeatedActivation}
                                onChange={setRepeatedActivation}
                                label="Show every time the event is captured"
                            />
                        </div>
                    </div>
                )}

                <div className="flex flex-wrap items-center gap-2 text-sm mt-5">
                    <span>Then wait</span>
                    <LemonInput
                        type="number"
                        min={0}
                        value={delaySeconds}
                        onChange={(val) => setDelaySeconds(Number(val) || 0)}
                        className="w-20 tabular-nums"
                    />
                    <span className="text-secondary">seconds before showing it.</span>
                </div>
            </WizardSection>

            <WizardSection
                title="How often should this survey show?"
                description="How many times the same user can see this survey, and how often."
                descriptionClassName="text-sm"
            >
                {repeatsOnEveryEvent ? (
                    <div className="text-sm" data-attr="survey-schedule-repeats-on-event-note">
                        <IconInfo className="mr-0.5" />
                        This survey is displayed whenever the{' '}
                        <LemonSnack>{triggerEvents.map((event) => event.name).join(', ')}</LemonSnack>{' '}
                        {triggerEvents.length === 1 ? 'event is' : 'events are'} captured, so the schedule options don't
                        apply. To set a schedule instead, uncheck 'Show every time the event is captured' above.
                    </div>
                ) : (
                    <>
                        <LemonSegmentedButton
                            value={frequency}
                            onChange={setFrequency}
                            options={FREQUENCY_OPTIONS.map((opt) => ({
                                ...opt,
                                tooltip:
                                    opt.value === recommendedFrequency.value
                                        ? `Recommended for this survey type`
                                        : undefined,
                            }))}
                            fullWidth
                        />

                        {recommendedFrequency.value === frequency && (
                            <p className="text-sm text-success mt-2 mb-0">{recommendedFrequency.reason}</p>
                        )}

                        {frequency !== 'once' && (
                            <div className="flex flex-wrap items-center gap-2 text-sm mt-5">
                                <span>Show up to</span>
                                <LemonInput
                                    type="number"
                                    min={MIN_ITERATION_COUNT}
                                    max={MAX_ITERATION_COUNT}
                                    value={iterationCount}
                                    onChange={(val) => setIterationCount(val ?? undefined)}
                                    onBlur={commitIterationCount}
                                    className="w-20 tabular-nums"
                                />
                                <span className="text-secondary">
                                    times in total ({MIN_ITERATION_COUNT}–{MAX_ITERATION_COUNT}).
                                </span>
                            </div>
                        )}
                    </>
                )}

                <div className="flex flex-wrap items-center gap-2 text-sm mt-5">
                    <LemonCheckbox
                        checked={seenSurveyWaitPeriodInDays != null}
                        onChange={(checked) => setSeenSurveyWaitPeriod(checked ? 30 : null)}
                        label="Don't show this survey if another one was shown to the user in the last"
                    />
                    <LemonInput
                        type="number"
                        min={1}
                        value={seenSurveyWaitPeriodInDays ?? undefined}
                        onChange={setSeenSurveyWaitPeriod}
                        className="w-20 tabular-nums"
                    />
                    <span className="text-secondary">days.</span>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-sm mt-3">
                    <LemonCheckbox
                        checked={survey.responses_limit != null}
                        onChange={(checked) => setResponsesLimit(checked ? 100 : null)}
                        label="Stop after"
                    />
                    <LemonInput
                        type="number"
                        min={1}
                        value={survey.responses_limit ?? undefined}
                        onChange={setResponsesLimit}
                        className="w-20 tabular-nums"
                    />
                    <span className="text-secondary">completed responses.</span>
                </div>
            </WizardSection>
        </WizardStepLayout>
    )
}
