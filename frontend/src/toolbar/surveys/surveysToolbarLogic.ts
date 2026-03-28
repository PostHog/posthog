import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { joinWithUiHost } from '~/toolbar/utils'
import { Survey, SurveyAppearance, SurveyMatchType, SurveyQuestionType, SurveySchedule, SurveyType } from '~/types'

import type { surveysToolbarLogicType } from './surveysToolbarLogicType'

export type SurveyStatus = 'draft' | 'active' | 'complete'

export type QuickSurveyQuestionType = 'open' | 'rating' | 'single_choice'

export type TargetingMode = 'all' | 'specific'
export type FrequencyOption = 'once' | 'yearly' | 'quarterly' | 'monthly'
export type TriggerMode = 'pageview' | 'event'

export const FREQUENCY_OPTIONS: { value: FrequencyOption; days: number | undefined; label: string }[] = [
    { value: 'once', days: undefined, label: 'Once' },
    { value: 'yearly', days: 365, label: 'Yearly' },
    { value: 'quarterly', days: 90, label: 'Quarterly' },
    { value: 'monthly', days: 30, label: 'Monthly' },
]

export interface QuickSurveyForm {
    name: string
    questionType: QuickSurveyQuestionType
    questionText: string
    ratingScale: 5 | 10
    ratingLowerLabel: string
    ratingUpperLabel: string
    choices: string[]
    // Where
    targetingMode: TargetingMode
    urlMatch: string
    // When - frequency
    frequency: FrequencyOption
    // When - trigger
    triggerMode: TriggerMode
    triggerEventName: string
    delaySeconds: number
}

export const EMPTY_FORM: QuickSurveyForm = {
    name: '',
    questionType: 'open',
    questionText: '',
    ratingScale: 5,
    ratingLowerLabel: 'Not likely',
    ratingUpperLabel: 'Very likely',
    choices: ['', ''],
    targetingMode: 'specific',
    urlMatch: '',
    frequency: 'once',
    triggerMode: 'pageview',
    triggerEventName: '',
    delaySeconds: 0,
}

export function getSurveyStatus(survey: Survey): SurveyStatus {
    if (!survey.start_date) {
        return 'draft'
    }
    if (survey.end_date) {
        return 'complete'
    }
    return 'active'
}

function buildSurveyPayload(form: QuickSurveyForm): Record<string, unknown> {
    const questions: Record<string, unknown>[] = []

    if (form.questionType === 'open') {
        questions.push({
            type: SurveyQuestionType.Open,
            question: form.questionText,
            buttonText: 'Submit',
        })
    } else if (form.questionType === 'rating') {
        questions.push({
            type: SurveyQuestionType.Rating,
            question: form.questionText,
            display: 'number',
            scale: form.ratingScale,
            lowerBoundLabel: form.ratingLowerLabel,
            upperBoundLabel: form.ratingUpperLabel,
            buttonText: 'Submit',
        })
    } else if (form.questionType === 'single_choice') {
        questions.push({
            type: SurveyQuestionType.SingleChoice,
            question: form.questionText,
            choices: form.choices.filter((c) => c.trim() !== ''),
            buttonText: 'Submit',
        })
    }

    // Build conditions
    const conditions: Record<string, unknown> = {}
    if (form.targetingMode === 'specific' && form.urlMatch) {
        conditions.url = form.urlMatch
        conditions.urlMatchType = SurveyMatchType.Contains
    }
    const frequencyOption = FREQUENCY_OPTIONS.find((o) => o.value === form.frequency)
    if (frequencyOption?.days) {
        conditions.seenSurveyWaitPeriodInDays = frequencyOption.days
    }
    if (form.triggerMode === 'event' && form.triggerEventName.trim()) {
        conditions.events = {
            values: [{ name: form.triggerEventName.trim() }],
            repeatedActivation: false,
        }
    }

    // Schedule
    const schedule = form.frequency === 'once' ? SurveySchedule.Once : SurveySchedule.Always

    return {
        name: form.name,
        type: SurveyType.Popover,
        questions,
        schedule,
        appearance: {
            fontFamily: 'inherit',
            backgroundColor: '#eeeded',
            submitButtonColor: 'black',
            submitButtonTextColor: 'white',
            ratingButtonColor: 'white',
            ratingButtonActiveColor: 'black',
            borderColor: '#c9c6c6',
            placeholder: 'Start typing...',
            displayThankYouMessage: true,
            thankYouMessageHeader: 'Thank you for your feedback!',
            position: 'right',
            zIndex: '2147482647',
            maxWidth: '300px',
            boxPadding: '20px 24px',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
            borderRadius: '10px',
            ...(form.delaySeconds > 0 ? { surveyPopupDelaySeconds: form.delaySeconds } : {}),
        },
        conditions: Object.keys(conditions).length > 0 ? conditions : null,
        start_date: null,
    }
}

export const surveysToolbarLogic = kea<surveysToolbarLogicType>([
    path(['toolbar', 'surveys', 'surveysToolbarLogic']),

    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        showButtonSurveys: true,
        hideButtonSurveys: true,
        // Quick-create flow
        startQuickCreate: true,
        cancelQuickCreate: true,
        setFormField: (field: keyof QuickSurveyForm, value: unknown) => ({ field, value }),
        submitQuickCreate: (launch: boolean = false) => ({ launch }),
        submitQuickCreateSuccess: true,
        submitQuickCreateFailure: true,
        // Live preview
        previewLiveSurvey: (surveyId: string) => ({ surveyId }),
        stopLivePreview: true,
    }),

    loaders(({ values }) => ({
        allSurveys: [
            [] as Survey[],
            {
                loadSurveys: async () => {
                    const params = new URLSearchParams()
                    params.set('archived', 'false')
                    if (values.searchTerm) {
                        params.set('search', values.searchTerm)
                    }
                    const url = `/api/projects/@current/surveys/?${params}`
                    const response = await toolbarFetch(url)
                    if (!response.ok) {
                        return []
                    }
                    const data = await response.json()
                    return data.results ?? data
                },
            },
        ],
    })),

    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        isCreating: [
            false,
            {
                startQuickCreate: () => true,
                cancelQuickCreate: () => false,
                submitQuickCreateSuccess: () => false,
            },
        ],
        quickForm: [
            { ...EMPTY_FORM } as QuickSurveyForm,
            {
                startQuickCreate: () => ({
                    ...EMPTY_FORM,
                    urlMatch: window.location.pathname,
                }),
                cancelQuickCreate: () => ({ ...EMPTY_FORM }),
                setFormField: (state, { field, value }) => ({
                    ...state,
                    [field]: value,
                }),
                submitQuickCreateSuccess: () => ({ ...EMPTY_FORM }),
            },
        ],
        isSubmitting: [
            false,
            {
                submitQuickCreate: () => true,
                submitQuickCreateSuccess: () => false,
                submitQuickCreateFailure: () => false,
            },
        ],
        livePreviewSurveyId: [
            null as string | null,
            {
                previewLiveSurvey: (_, { surveyId }) => surveyId,
                stopLivePreview: () => null,
                startQuickCreate: () => null,
            },
        ],
    }),

    selectors({
        previewSurvey: [
            (s) => [s.quickForm, s.isCreating],
            (form, isCreating): Survey | null => {
                if (!isCreating) {
                    return null
                }
                const previewForm: QuickSurveyForm = {
                    ...form,
                    questionText: form.questionText || 'Your question will appear here',
                    name: form.name || 'Untitled survey',
                }
                const payload = buildSurveyPayload(previewForm)
                return {
                    id: 'preview',
                    name: previewForm.name,
                    description: '',
                    type: SurveyType.Popover,
                    questions: payload.questions as Survey['questions'],
                    appearance: (payload.appearance as SurveyAppearance) ?? null,
                    conditions: (payload.conditions as Survey['conditions']) ?? null,
                    start_date: null,
                    end_date: null,
                    created_at: new Date().toISOString(),
                    feature_flag_keys: null,
                    linked_flag_key: null,
                    targeting_flag_key: null,
                    internal_targeting_flag_key: null,
                    linked_flag: null,
                    targeting_flag: null,
                    internal_targeting_flag: null,
                    responses_limit: null,
                    iteration_count: null,
                    iteration_frequency_days: null,
                    iteration_start_dates: null,
                    current_iteration: null,
                    current_iteration_start_date: null,
                } as Survey
            },
        ],
        canProceed: [
            (s) => [s.quickForm],
            (form): boolean => {
                return (
                    !!form.name.trim() &&
                    !!form.questionText.trim() &&
                    (form.questionType !== 'single_choice' ||
                        form.choices.filter((c: string) => c.trim() !== '').length >= 2)
                )
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        startQuickCreate: () => {
            toolbarLogic.actions.setVisibleMenu('none')
        },
        setSearchTerm: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadSurveys()
        },
        previewLiveSurvey: ({ surveyId }) => {
            const { posthog } = toolbarConfigLogic.values
            if (!posthog?.surveys) {
                lemonToast.error('PostHog JS SDK not available')
                return
            }
            if (typeof posthog.surveys.displaySurvey !== 'function') {
                lemonToast.error('Survey preview requires a newer version of posthog-js')
                return
            }
            toolbarLogic.actions.toggleMinimized(true)
            posthog.surveys.displaySurvey(surveyId, {
                ignoreConditions: true,
                ignoreDelay: true,
                displayType: 'popover',
            })
            toolbarPosthogJS.capture('toolbar survey previewed', { survey_id: surveyId })
        },
        stopLivePreview: () => {
            toolbarLogic.actions.toggleMinimized(false)
        },
        submitQuickCreate: async ({ launch }) => {
            const payload = buildSurveyPayload(values.quickForm)
            if (launch) {
                payload.start_date = new Date().toISOString()
            }
            try {
                const response = await toolbarFetch('/api/projects/@current/surveys/', 'POST', payload)
                if (!response.ok) {
                    const error = await response.json()
                    lemonToast.error(error.detail || 'Failed to create survey')
                    actions.submitQuickCreateFailure()
                    return
                }
                const saved = await response.json()
                toolbarPosthogJS.capture('toolbar survey created', {
                    question_type: values.quickForm.questionType,
                    has_url_targeting: values.quickForm.targetingMode === 'specific',
                    frequency: values.quickForm.frequency,
                    trigger_mode: values.quickForm.triggerMode,
                    launched: launch,
                })
                const { uiHost } = toolbarConfigLogic.values
                const surveyUrl = joinWithUiHost(uiHost, `/surveys/${saved.id}`)
                lemonToast.success(launch ? 'Survey launched!' : 'Survey draft created!', {
                    button: {
                        label: 'Open in PostHog',
                        action: () => window.open(surveyUrl, '_blank'),
                    },
                })
                actions.submitQuickCreateSuccess()
                actions.loadSurveys()
            } catch {
                lemonToast.error('Failed to create survey')
                actions.submitQuickCreateFailure()
            }
        },
    })),
])
