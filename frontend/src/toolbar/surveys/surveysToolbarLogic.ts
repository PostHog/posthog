import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

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

const SURVEYS_PAGE_SIZE = 20

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

/**
 * Whether the quick-create form can represent this survey faithfully. Used to
 * gate the edit button — we only allow editing single-question popover surveys
 * whose question type maps to one of our form options.
 */
export function isQuickEditable(survey: Survey): boolean {
    if (survey.type !== SurveyType.Popover) {
        return false
    }
    if (survey.questions.length !== 1) {
        return false
    }
    const q = survey.questions[0]
    return (
        q.type === SurveyQuestionType.Open ||
        q.type === SurveyQuestionType.Rating ||
        q.type === SurveyQuestionType.SingleChoice
    )
}

function surveyToForm(survey: Survey): QuickSurveyForm {
    const q = survey.questions[0]
    let questionType: QuickSurveyQuestionType = 'open'
    let ratingScale: 5 | 10 = 5
    let ratingLowerLabel = EMPTY_FORM.ratingLowerLabel
    let ratingUpperLabel = EMPTY_FORM.ratingUpperLabel
    let choices: string[] = ['', '']

    if (q.type === SurveyQuestionType.Rating) {
        questionType = 'rating'
        ratingScale = q.scale === 10 ? 10 : 5
        ratingLowerLabel = q.lowerBoundLabel ?? ratingLowerLabel
        ratingUpperLabel = q.upperBoundLabel ?? ratingUpperLabel
    } else if (q.type === SurveyQuestionType.SingleChoice) {
        questionType = 'single_choice'
        choices = q.choices && q.choices.length >= 2 ? [...q.choices] : ['', '']
    }

    const conditions = survey.conditions ?? null
    const targetingMode: TargetingMode = conditions?.url ? 'specific' : 'all'
    const urlMatch = conditions?.url ?? ''

    let frequency: FrequencyOption = 'once'
    if (conditions?.seenSurveyWaitPeriodInDays) {
        frequency = FREQUENCY_OPTIONS.find((o) => o.days === conditions.seenSurveyWaitPeriodInDays)?.value ?? 'once'
    }

    let triggerMode: TriggerMode = 'pageview'
    let triggerEventName = ''
    const eventValues = conditions?.events?.values
    if (eventValues && eventValues.length > 0) {
        triggerMode = 'event'
        triggerEventName = eventValues[0].name
    }

    const delaySeconds = ((survey.appearance as SurveyAppearance | null)?.surveyPopupDelaySeconds as number) || 0

    return {
        name: survey.name,
        questionType,
        questionText: q.question,
        ratingScale,
        ratingLowerLabel,
        ratingUpperLabel,
        choices,
        targetingMode,
        urlMatch,
        frequency,
        triggerMode,
        triggerEventName,
        delaySeconds,
    }
}

async function patchAndRefreshSurvey(
    surveyId: string,
    payload: Record<string, unknown>,
    successMessage: string
): Promise<void> {
    try {
        const response = await toolbarFetch(`/api/projects/@current/surveys/${surveyId}/`, 'PATCH', payload)
        if (!response.ok) {
            const error = await response.json().catch(() => ({}))
            lemonToast.error(error.detail || 'Failed to update survey')
            return
        }
        lemonToast.success(successMessage)
    } catch {
        lemonToast.error('Failed to update survey')
    }
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
        // Quick-create / quick-edit flow (shares the same sidebar form)
        startQuickCreate: true,
        startQuickEdit: (survey: Survey) => ({ survey }),
        cancelQuickCreate: true,
        setFormField: (field: keyof QuickSurveyForm, value: unknown) => ({ field, value }),
        submitQuickCreate: (launch: boolean = false) => ({ launch }),
        submitQuickCreateSuccess: true,
        submitQuickCreateFailure: true,
        // Lifecycle (launch / stop / resume / archive)
        launchSurvey: (survey: Survey) => ({ survey }),
        stopSurvey: (survey: Survey) => ({ survey }),
        resumeSurvey: (survey: Survey) => ({ survey }),
        archiveSurvey: (survey: Survey) => ({ survey }),
        // Pagination — loadMoreSurveys is auto-declared by the loader below
        setHasMoreSurveys: (hasMore: boolean) => ({ hasMore }),
    }),

    loaders(({ values, actions }) => ({
        allSurveys: [
            [] as Survey[],
            {
                loadSurveys: async () => {
                    const params = new URLSearchParams()
                    params.set('archived', 'false')
                    params.set('limit', String(SURVEYS_PAGE_SIZE))
                    params.set('offset', '0')
                    if (values.searchTerm) {
                        params.set('search', values.searchTerm)
                    }
                    const url = `/api/projects/@current/surveys/?${params}`
                    const response = await toolbarFetch(url)
                    if (!response.ok) {
                        actions.setHasMoreSurveys(false)
                        return []
                    }
                    const data = await response.json()
                    actions.setHasMoreSurveys(!!data.next)
                    return data.results ?? data
                },
                loadMoreSurveys: async () => {
                    if (!values.hasMoreSurveys || values.allSurveysLoading) {
                        return values.allSurveys
                    }
                    const params = new URLSearchParams()
                    params.set('archived', 'false')
                    params.set('limit', String(SURVEYS_PAGE_SIZE))
                    params.set('offset', String(values.allSurveys.length))
                    if (values.searchTerm) {
                        params.set('search', values.searchTerm)
                    }
                    const url = `/api/projects/@current/surveys/?${params}`
                    const response = await toolbarFetch(url)
                    if (!response.ok) {
                        return values.allSurveys
                    }
                    const data = await response.json()
                    actions.setHasMoreSurveys(!!data.next)
                    return [...values.allSurveys, ...(data.results ?? [])]
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
                startQuickEdit: () => true,
                cancelQuickCreate: () => false,
                submitQuickCreateSuccess: () => false,
            },
        ],
        editingSurveyId: [
            null as string | null,
            {
                startQuickCreate: () => null,
                startQuickEdit: (_, { survey }) => survey.id,
                cancelQuickCreate: () => null,
                submitQuickCreateSuccess: () => null,
            },
        ],
        quickForm: [
            { ...EMPTY_FORM } as QuickSurveyForm,
            {
                startQuickCreate: () => ({
                    ...EMPTY_FORM,
                    urlMatch: window.location.pathname,
                }),
                startQuickEdit: (_, { survey }) => surveyToForm(survey),
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
        hasMoreSurveys: [
            false,
            {
                setHasMoreSurveys: (_, { hasMore }) => hasMore,
                loadSurveys: () => false,
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
                // Build the minimal shape that the surveys preview renderer reads.
                // Cast through `unknown` so we don't have to pretend to satisfy
                // every Survey field (created_by, archived, linked_flag_id, etc.).
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
                    linked_flag: null,
                    targeting_flag: null,
                    responses_limit: null,
                } as unknown as Survey
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
        startQuickEdit: () => {
            toolbarLogic.actions.setVisibleMenu('none')
        },
        setSearchTerm: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadSurveys()
        },
        launchSurvey: async ({ survey }) => {
            await patchAndRefreshSurvey(survey.id, { start_date: new Date().toISOString() }, 'Survey launched')
            actions.loadSurveys()
            actions.cancelQuickCreate()
        },
        stopSurvey: async ({ survey }) => {
            await patchAndRefreshSurvey(survey.id, { end_date: new Date().toISOString() }, 'Survey stopped')
            actions.loadSurveys()
            actions.cancelQuickCreate()
        },
        resumeSurvey: async ({ survey }) => {
            await patchAndRefreshSurvey(survey.id, { end_date: null }, 'Survey resumed')
            actions.loadSurveys()
            actions.cancelQuickCreate()
        },
        archiveSurvey: async ({ survey }) => {
            await patchAndRefreshSurvey(survey.id, { archived: true }, 'Survey archived')
            actions.loadSurveys()
            actions.cancelQuickCreate()
        },
        submitQuickCreate: async ({ launch }) => {
            const editingId = values.editingSurveyId
            const payload = buildSurveyPayload(values.quickForm)
            // When editing, "Launch" forces start_date to now; "Save" preserves
            // the survey's current launch state (don't sneak-launch or sneak-end).
            if (launch) {
                payload.start_date = new Date().toISOString()
            } else if (editingId) {
                delete payload.start_date
            }
            try {
                const response = await toolbarFetch(
                    editingId ? `/api/projects/@current/surveys/${editingId}/` : '/api/projects/@current/surveys/',
                    editingId ? 'PATCH' : 'POST',
                    payload
                )
                if (!response.ok) {
                    const error = await response.json()
                    lemonToast.error(error.detail || (editingId ? 'Failed to save survey' : 'Failed to create survey'))
                    actions.submitQuickCreateFailure()
                    return
                }
                const saved = await response.json()
                toolbarPosthogJS.capture(editingId ? 'toolbar survey edited' : 'toolbar survey created', {
                    question_type: values.quickForm.questionType,
                    has_url_targeting: values.quickForm.targetingMode === 'specific',
                    frequency: values.quickForm.frequency,
                    trigger_mode: values.quickForm.triggerMode,
                    launched: launch,
                })
                const { uiHost } = toolbarConfigLogic.values
                const surveyUrl = joinWithUiHost(uiHost, urls.survey(saved.id))
                const message = editingId
                    ? launch
                        ? 'Survey saved and launched!'
                        : 'Survey saved!'
                    : launch
                      ? 'Survey launched!'
                      : 'Survey draft created!'
                lemonToast.success(message, {
                    button: {
                        label: 'Open in PostHog',
                        action: () => window.open(surveyUrl, '_blank'),
                    },
                })
                actions.submitQuickCreateSuccess()
                actions.loadSurveys()
            } catch {
                lemonToast.error(editingId ? 'Failed to save survey' : 'Failed to create survey')
                actions.submitQuickCreateFailure()
            }
        },
    })),
])
