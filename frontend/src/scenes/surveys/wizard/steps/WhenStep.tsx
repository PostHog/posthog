import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { SurveyEventSelector } from 'scenes/surveys/SurveyEventTrigger'

import {
    SurveyAppearance,
    SurveyDisplayConditions,
    SurveyPosition,
    SurveySchedule,
    SurveyTabPosition,
    SurveyType,
} from '~/types'

import { surveyLogic } from '../../surveyLogic'
import { surveyWizardLogic } from '../surveyWizardLogic'

const FREQUENCY_OPTIONS: { value: string; days: number | undefined; label: string }[] = [
    { value: 'once', days: undefined, label: 'Once ever' },
    { value: 'yearly', days: 365, label: 'Every year' },
    { value: 'quarterly', days: 90, label: 'Every 3 months' },
    { value: 'monthly', days: 30, label: 'Every month' },
]

export function WhenStep({ handleCustomizeMore }: { handleCustomizeMore: () => void }): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const { recommendedFrequency } = useValues(surveyWizardLogic)

    const conditions: Partial<SurveyDisplayConditions> = survey.conditions || {}
    const appearance: Partial<SurveyAppearance> = survey.appearance || {}
    const triggerMode = conditions.events !== null && conditions.events !== undefined ? 'event' : 'pageview'
    const repeatedActivation = conditions.events?.repeatedActivation ?? false
    const delaySeconds = appearance.surveyPopupDelaySeconds ?? 0
    const isWidget = survey.type === SurveyType.Widget

    const daysToFrequency = (days: number | undefined): string => {
        const option = FREQUENCY_OPTIONS.find((opt) => opt.days === days)
        return option?.value || 'monthly'
    }
    const frequency = daysToFrequency(conditions.seenSurveyWaitPeriodInDays)

    const onAppearanceChange = (updates: Partial<SurveyAppearance>): void => {
        setSurveyValue('appearance', { ...appearance, ...updates })
    }

    const setTriggerMode = (mode: 'pageview' | 'event'): void => {
        if (mode === 'pageview') {
            setSurveyValue('conditions', { ...conditions, events: null })
        } else {
            setSurveyValue('conditions', { ...conditions, events: { values: [], repeatedActivation: false } })
        }
    }

    const setDelaySeconds = (seconds: number): void => {
        onAppearanceChange({ surveyPopupDelaySeconds: seconds })
    }

    const setFrequency = (value: string): void => {
        const option = FREQUENCY_OPTIONS.find((opt) => opt.value === value)
        const isOnce = value === 'once'
        setSurveyValue('schedule', isOnce ? SurveySchedule.Once : SurveySchedule.Always)
        setSurveyValue('conditions', { ...conditions, seenSurveyWaitPeriodInDays: option?.days })
    }

    const showFrequency = !isWidget && (triggerMode === 'pageview' || (triggerMode === 'event' && !repeatedActivation))

    return (
        <div className="space-y-8">
            <div className="space-y-3">
                <div>
                    <h2 className="text-xl font-semibold mb-1">How should this survey appear?</h2>
                    <p className="text-secondary text-sm">
                        Looking for hosted surveys?{' '}
                        <button type="button" onClick={handleCustomizeMore} className="text-link hover:underline">
                            Open full editor
                        </button>
                    </p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                    <PresentationCard
                        selected={!isWidget}
                        onClick={() => {
                            setSurveyValue('type', SurveyType.Popover)
                            setSurveyValue('schedule', SurveySchedule.Once)
                            onAppearanceChange({ position: SurveyPosition.Right })
                        }}
                        title="Pop-up"
                        description="Appears in a corner of the page"
                        illustration={<PopupIllustration />}
                    />
                    <PresentationCard
                        selected={isWidget}
                        onClick={() => {
                            setSurveyValue('type', SurveyType.Widget)
                            setSurveyValue('schedule', SurveySchedule.Always)
                            setSurveyValue('conditions', {
                                ...conditions,
                                events: null,
                                seenSurveyWaitPeriodInDays: undefined,
                            })
                            onAppearanceChange({
                                position: SurveyPosition.NextToTrigger,
                                tabPosition: SurveyTabPosition.Right,
                                surveyPopupDelaySeconds: 0,
                            })
                        }}
                        title="Feedback button"
                        description="Persistent tab on the edge of the page"
                        illustration={<WidgetIllustration />}
                    />
                </div>
            </div>

            {isWidget && (
                <div className="space-y-2">
                    <LemonField.Pure label="Button label" className="gap-1">
                        <LemonInput
                            value={appearance.widgetLabel}
                            onChange={(widgetLabel) => onAppearanceChange({ widgetLabel })}
                            placeholder="Feedback"
                        />
                    </LemonField.Pure>
                </div>
            )}

            {!isWidget && (
                <>
                    <div className="space-y-3">
                        <div className="space-y-1">
                            <h2 className="text-xl font-semibold">When should this appear?</h2>
                            <p className="text-secondary text-sm">Choose when to show this survey to your users</p>
                        </div>

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
                            <div className="ml-6">
                                <SurveyEventSelector
                                    conditionField="events"
                                    label=""
                                    info=""
                                    emptyTitle="No events selected"
                                    emptyDescription="Add events to trigger this survey when those events are captured"
                                    addButtonText="Add event"
                                    showRepeatedActivation
                                />
                            </div>
                        )}

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Delay before showing</label>
                            <div className="flex items-center gap-2">
                                <LemonInput
                                    type="number"
                                    min={0}
                                    value={delaySeconds}
                                    onChange={(val) => setDelaySeconds(Number(val) || 0)}
                                    className="w-20"
                                />
                                <span className="text-secondary text-sm">seconds after conditions are met</span>
                            </div>
                            <p className="text-muted text-xs">
                                Once a user matches the targeting conditions, wait this long before displaying the
                                survey
                            </p>
                        </div>
                    </div>

                    {showFrequency && (
                        <div>
                            <h2 className="text-xl font-semibold mb-2">How often can someone see this?</h2>
                            <p className="text-secondary mb-6">
                                Control how frequently the same person can be shown this survey
                            </p>

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
                                <p className="text-sm text-success mt-3">{recommendedFrequency.reason}</p>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

function PresentationCard({
    selected,
    onClick,
    title,
    description,
    illustration,
}: {
    selected: boolean
    onClick: () => void
    title: string
    description: string
    illustration: JSX.Element
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'group relative flex flex-col items-center gap-2 rounded-lg border-2 p-3 text-center transition-all duration-200',
                'hover:scale-[1.02] active:scale-[0.98]',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-3000 focus-visible:ring-offset-2',
                selected
                    ? 'border-primary-3000 bg-fill-primary-highlight shadow-md'
                    : 'border-border bg-bg-light hover:border-primary-3000 hover:shadow-sm'
            )}
        >
            <div
                className={clsx(
                    'absolute -right-1.5 -top-1.5 flex h-6 w-6 items-center justify-center rounded-full transition-all duration-200 shadow-sm',
                    selected ? 'scale-100 bg-primary-3000' : 'scale-0 bg-transparent'
                )}
            >
                <IconCheck className="h-3.5 w-3.5 text-primary-inverse" />
            </div>
            {illustration}
            <div>
                <div className="text-sm font-medium">{title}</div>
                <div className="text-xs text-muted">{description}</div>
            </div>
        </button>
    )
}

function PopupIllustration(): JSX.Element {
    return (
        <svg width="80" height="52" viewBox="0 0 80 52" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect
                x="0.5"
                y="0.5"
                width="79"
                height="51"
                rx="4"
                fill="currentColor"
                fillOpacity={0.03}
                stroke="currentColor"
                strokeOpacity={0.15}
            />
            <rect
                x="0.5"
                y="0.5"
                width="79"
                height="8"
                rx="4"
                fill="currentColor"
                fillOpacity={0.05}
                stroke="currentColor"
                strokeOpacity={0.15}
            />
            <circle cx="7" cy="5" r="1.5" fill="currentColor" fillOpacity={0.2} />
            <circle cx="12" cy="5" r="1.5" fill="currentColor" fillOpacity={0.2} />
            <circle cx="17" cy="5" r="1.5" fill="currentColor" fillOpacity={0.2} />
            <rect x="6" y="14" width="30" height="2" rx="1" fill="currentColor" fillOpacity={0.08} />
            <rect x="6" y="19" width="22" height="2" rx="1" fill="currentColor" fillOpacity={0.06} />
            <rect
                x="44"
                y="22"
                width="30"
                height="25"
                rx="3"
                fill="var(--primary-3000)"
                fillOpacity={0.12}
                stroke="var(--primary-3000)"
                strokeOpacity={0.4}
            />
            <rect x="48" y="26" width="16" height="1.5" rx="0.75" fill="var(--primary-3000)" fillOpacity={0.5} />
            <rect x="48" y="30" width="22" height="1.5" rx="0.75" fill="var(--primary-3000)" fillOpacity={0.3} />
            <rect x="48" y="33" width="18" height="1.5" rx="0.75" fill="var(--primary-3000)" fillOpacity={0.3} />
            <rect x="48" y="39" width="22" height="5" rx="2" fill="var(--primary-3000)" fillOpacity={0.35} />
        </svg>
    )
}

function WidgetIllustration(): JSX.Element {
    return (
        <svg width="80" height="52" viewBox="0 0 80 52" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect
                x="0.5"
                y="0.5"
                width="79"
                height="51"
                rx="4"
                fill="currentColor"
                fillOpacity={0.03}
                stroke="currentColor"
                strokeOpacity={0.15}
            />
            <rect
                x="0.5"
                y="0.5"
                width="79"
                height="8"
                rx="4"
                fill="currentColor"
                fillOpacity={0.05}
                stroke="currentColor"
                strokeOpacity={0.15}
            />
            <circle cx="7" cy="5" r="1.5" fill="currentColor" fillOpacity={0.2} />
            <circle cx="12" cy="5" r="1.5" fill="currentColor" fillOpacity={0.2} />
            <circle cx="17" cy="5" r="1.5" fill="currentColor" fillOpacity={0.2} />
            <rect x="6" y="14" width="30" height="2" rx="1" fill="currentColor" fillOpacity={0.08} />
            <rect x="6" y="19" width="22" height="2" rx="1" fill="currentColor" fillOpacity={0.06} />
            <rect
                x="64"
                y="20"
                width="16"
                height="24"
                rx="3"
                fill="var(--primary-3000)"
                fillOpacity={0.12}
                stroke="var(--primary-3000)"
                strokeOpacity={0.4}
            />
            <rect x="68" y="28" width="2" height="8" rx="1" fill="var(--primary-3000)" fillOpacity={0.5} />
        </svg>
    )
}
