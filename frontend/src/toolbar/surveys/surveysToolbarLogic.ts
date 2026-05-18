import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { joinWithUiHost } from '~/toolbar/utils'
import {
    Survey,
    SurveyAppearance,
    SurveyMatchType,
    SurveyPosition,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import type { surveysToolbarLogicType } from './surveysToolbarLogicType'

export type SurveyStatus = 'draft' | 'active' | 'complete'

export type QuickSurveyQuestionType = 'open' | 'rating' | 'single_choice'

export type TargetingMode = 'all' | 'specific'
export type FrequencyOption = 'once' | 'yearly' | 'quarterly' | 'monthly'
export type TriggerMode = 'pageview' | 'event'

const SURVEYS_PAGE_SIZE = 20
export const SURVEY_PREVIEW_Z_INDEX = 2147482647
export const SURVEY_DELAY_MAX_SECONDS = 3600
export const SURVEY_NAME_MAX_LENGTH = 200
export const SURVEY_QUESTION_MAX_LENGTH = 1000
export const SURVEY_CHOICE_MAX_LENGTH = 200
export const SURVEY_QUICK_FORM_MAX_CHOICES = 6

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
    urlMatchType: SurveyMatchType
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
    // Default to exact for the auto-filled current page — users targeting "this
    // page" usually mean exactly that, not contains.
    urlMatchType: SurveyMatchType.Exact,
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
 * Whether the quick-create form can faithfully round-trip this survey. We
 * deliberately reject anything we can't represent exactly so an "Edit in
 * toolbar" save never silently drops or downgrades data.
 */
export function isQuickEditable(survey: Survey): boolean {
    if (survey.type !== SurveyType.Popover) {
        return false
    }
    if (survey.questions.length !== 1) {
        return false
    }
    const q = survey.questions[0]
    const isSupportedType =
        q.type === SurveyQuestionType.Open ||
        q.type === SurveyQuestionType.Rating ||
        q.type === SurveyQuestionType.SingleChoice
    if (!isSupportedType) {
        return false
    }
    // Single-choice surveys with non-empty answer set within our cap. Empty
    // strings here would get silently filtered on save.
    if (q.type === SurveyQuestionType.SingleChoice) {
        const choices = q.choices ?? []
        if (choices.length === 0 || choices.length > SURVEY_QUICK_FORM_MAX_CHOICES) {
            return false
        }
        if (choices.some((c) => !c || !c.trim())) {
            return false
        }
    }
    // Rating: only the scale values our form exposes.
    if (q.type === SurveyQuestionType.Rating) {
        const scale = q.scale
        if (scale !== 5 && scale !== 10) {
            return false
        }
    }
    // Frequency must map to one of the form's options — anything else (e.g.
    // a custom 60-day cadence) would silently downgrade to "Once" on save.
    const wait = survey.conditions?.seenSurveyWaitPeriodInDays
    if (wait !== undefined && wait !== null && !FREQUENCY_OPTIONS.some((o) => o.days === wait)) {
        return false
    }
    return true
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
    const urlMatchType = conditions?.urlMatchType ?? EMPTY_FORM.urlMatchType

    let frequency: FrequencyOption = 'once'
    if (conditions?.seenSurveyWaitPeriodInDays) {
        frequency = FREQUENCY_OPTIONS.find((o) => o.days === conditions.seenSurveyWaitPeriodInDays)?.value ?? 'once'
    }

    let triggerMode: TriggerMode = 'pageview'
    let triggerEventName = ''
    const eventValues = conditions?.events?.values
    if (eventValues && eventValues.length > 0) {
        triggerMode = 'event'
        triggerEventName = eventValues[0]?.name ?? ''
    }

    const rawDelay = (survey.appearance as SurveyAppearance | null)?.surveyPopupDelaySeconds
    const delaySeconds = clampDelaySeconds(rawDelay)

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
        urlMatchType,
        frequency,
        triggerMode,
        triggerEventName,
        delaySeconds,
    }
}

export function clampDelaySeconds(value: unknown): number {
    const n = typeof value === 'number' ? value : Number(value)
    if (!Number.isFinite(n) || n <= 0) {
        return 0
    }
    return Math.min(SURVEY_DELAY_MAX_SECONDS, Math.floor(n))
}

const DEFAULT_APPEARANCE: SurveyAppearance = {
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
    position: SurveyPosition.Right,
    zIndex: String(SURVEY_PREVIEW_Z_INDEX),
    maxWidth: '300px',
    boxPadding: '20px 24px',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    borderRadius: '10px',
}

interface BuildPayloadOptions {
    /** When set, merge form-controlled fields onto the existing survey's
     *  appearance/conditions instead of overwriting with defaults. */
    existing?: Survey | null
}

function buildSurveyPayload(form: QuickSurveyForm, opts: BuildPayloadOptions = {}): Record<string, unknown> {
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

    // Conditions: when editing, preserve fields the form doesn't model
    // (selector, deviceTypes, actions, cancelEvents, linkedFlagVariant, etc.).
    const existingConditions = opts.existing?.conditions ?? null
    const baseConditions: Record<string, unknown> = existingConditions ? { ...existingConditions } : {}

    // URL targeting — completely controlled by the form.
    if (form.targetingMode === 'specific' && form.urlMatch) {
        baseConditions.url = form.urlMatch
        baseConditions.urlMatchType = form.urlMatchType
    } else {
        delete baseConditions.url
        delete baseConditions.urlMatchType
    }

    // Frequency — completely controlled by the form.
    const frequencyOption = FREQUENCY_OPTIONS.find((o) => o.value === form.frequency)
    if (frequencyOption?.days) {
        baseConditions.seenSurveyWaitPeriodInDays = frequencyOption.days
    } else {
        delete baseConditions.seenSurveyWaitPeriodInDays
    }

    // Event trigger — controlled by the form. Preserve repeatedActivation if
    // the existing survey had one.
    if (form.triggerMode === 'event' && form.triggerEventName.trim()) {
        const previousRepeated =
            (existingConditions?.events as { repeatedActivation?: boolean } | null | undefined)?.repeatedActivation ??
            false
        baseConditions.events = {
            values: [{ name: form.triggerEventName.trim() }],
            repeatedActivation: previousRepeated,
        }
    } else {
        delete baseConditions.events
    }

    const conditions = Object.keys(baseConditions).length > 0 ? baseConditions : null

    // Appearance: when editing, only the fields the form controls (currently
    // surveyPopupDelaySeconds) should change. When creating, seed from defaults.
    const baseAppearance: Record<string, unknown> = opts.existing?.appearance
        ? { ...(opts.existing.appearance as Record<string, unknown>) }
        : { ...(DEFAULT_APPEARANCE as Record<string, unknown>) }
    if (form.delaySeconds > 0) {
        baseAppearance.surveyPopupDelaySeconds = form.delaySeconds
    } else {
        delete baseAppearance.surveyPopupDelaySeconds
    }

    // Schedule
    const schedule = form.frequency === 'once' ? SurveySchedule.Once : SurveySchedule.Always

    const payload: Record<string, unknown> = {
        name: form.name,
        questions,
        schedule,
        appearance: baseAppearance,
        conditions,
    }
    if (!opts.existing) {
        // New survey — set type and start as draft.
        payload.type = SurveyType.Popover
        payload.start_date = null
    }
    return payload
}

async function patchAndRefreshSurvey(
    surveyId: string,
    payload: Record<string, unknown>,
    successMessage: string
): Promise<boolean> {
    try {
        const response = await toolbarFetch(`/api/projects/@current/surveys/${surveyId}/`, 'PATCH', payload)
        if (!response.ok) {
            const error = await response.json().catch(() => ({}))
            lemonToast.error(formatApiError(error, response.status, 'Failed to update survey'))
            return false
        }
        lemonToast.success(successMessage)
        return true
    } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[Toolbar] survey lifecycle update failed', e)
        lemonToast.error('Failed to update survey')
        return false
    }
}

function formatApiError(error: unknown, status: number, fallback: string): string {
    if (status === 401 || status === 403) {
        return 'Your toolbar session lacks permission. Please re-authenticate the toolbar from PostHog.'
    }
    if (error && typeof error === 'object') {
        const errObj = error as Record<string, unknown>
        if (typeof errObj.detail === 'string' && errObj.detail) {
            return errObj.detail
        }
        // Surface DRF field-level errors: { name: ["..."], questions: [...] }.
        const fieldMessages: string[] = []
        for (const [key, value] of Object.entries(errObj)) {
            if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'string') {
                fieldMessages.push(`${key}: ${value[0]}`)
            } else if (typeof value === 'string') {
                fieldMessages.push(`${key}: ${value}`)
            }
        }
        if (fieldMessages.length > 0) {
            return fieldMessages.join('; ')
        }
    }
    return fallback
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
        setLifecyclePending: (pending: boolean) => ({ pending }),
        // Pagination — loadMoreSurveys is auto-declared by the loader below
        setHasMoreSurveys: (hasMore: boolean) => ({ hasMore }),
    }),

    loaders(({ values, actions }) => ({
        allSurveys: [
            [] as Survey[],
            {
                loadSurveys: async () => {
                    const search = values.searchTerm
                    const params = new URLSearchParams()
                    params.set('archived', 'false')
                    params.set('limit', String(SURVEYS_PAGE_SIZE))
                    params.set('offset', '0')
                    if (search) {
                        params.set('search', search)
                    }
                    const url = `/api/projects/@current/surveys/?${params}`
                    const response = await toolbarFetch(url)
                    // If the search term changed while we were awaiting,
                    // abandon this result to avoid clobbering newer state.
                    if (search !== values.searchTerm) {
                        return values.allSurveys
                    }
                    if (!response.ok) {
                        actions.setHasMoreSurveys(false)
                        return []
                    }
                    const data = await response.json().catch(() => ({}))
                    actions.setHasMoreSurveys(!!data.next)
                    return data.results ?? data ?? []
                },
                loadMoreSurveys: async () => {
                    if (!values.hasMoreSurveys || values.allSurveysLoading) {
                        return values.allSurveys
                    }
                    const search = values.searchTerm
                    const previousIds = new Set(values.allSurveys.map((s) => s.id))
                    const params = new URLSearchParams()
                    params.set('archived', 'false')
                    params.set('limit', String(SURVEYS_PAGE_SIZE))
                    params.set('offset', String(values.allSurveys.length))
                    if (search) {
                        params.set('search', search)
                    }
                    const url = `/api/projects/@current/surveys/?${params}`
                    const response = await toolbarFetch(url)
                    // Search changed while we were paging — drop the result.
                    if (search !== values.searchTerm) {
                        return values.allSurveys
                    }
                    if (!response.ok) {
                        return values.allSurveys
                    }
                    const data = await response.json().catch(() => ({}))
                    actions.setHasMoreSurveys(!!data.next)
                    const newRows: Survey[] = (data.results ?? data ?? []).filter((s: Survey) => !previousIds.has(s.id))
                    return [...values.allSurveys, ...newRows]
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
        // Snapshot the survey at edit-start so we don't depend on it being
        // present in `allSurveys` (the list can reload mid-edit).
        editingSurvey: [
            null as Survey | null,
            {
                startQuickCreate: () => null,
                startQuickEdit: (_, { survey }) => survey,
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
                    urlMatchType: SurveyMatchType.Exact,
                }),
                startQuickEdit: (_, { survey }) => surveyToForm(survey),
                cancelQuickCreate: () => ({ ...EMPTY_FORM }),
                setFormField: (state, { field, value }) => {
                    if (field === 'delaySeconds') {
                        return { ...state, delaySeconds: clampDelaySeconds(value) }
                    }
                    return { ...state, [field]: value as never }
                },
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
        isLifecyclePending: [
            false,
            {
                setLifecyclePending: (_, { pending }) => pending,
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
            (s) => [s.quickForm, s.isCreating, s.editingSurvey],
            (form, isCreating, editingSurvey): Survey | null => {
                if (!isCreating) {
                    return null
                }
                const previewForm: QuickSurveyForm = {
                    ...form,
                    questionText: form.questionText || 'Your question will appear here',
                    name: form.name || 'Untitled survey',
                }
                const payload = buildSurveyPayload(previewForm, { existing: editingSurvey })
                // Build the minimal shape that the surveys preview renderer reads.
                // Cast through `unknown` so we don't have to pretend to satisfy
                // every Survey field (created_by, archived, linked_flag_id, etc.).
                // No wall-clock fields here — the selector must be referentially
                // stable when inputs are unchanged so downstream effects can dedupe.
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
                    created_at: '1970-01-01T00:00:00.000Z',
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
        // Surface a concrete reason the submit button is disabled — generic
        // "Fill in the name and question" misleads users who are stuck on
        // "needs at least two single-choice options".
        canProceedReason: [
            (s) => [s.quickForm],
            (form): string | null => {
                if (!form.name.trim()) {
                    return 'Add a survey name'
                }
                if (!form.questionText.trim()) {
                    return 'Add a question'
                }
                if (form.questionType === 'single_choice') {
                    const filled = form.choices.filter((c) => c.trim() !== '').length
                    if (filled < 2) {
                        return 'Add at least two answer options'
                    }
                }
                return null
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
            if (values.isLifecyclePending) {
                return
            }
            actions.setLifecyclePending(true)
            const ok = await patchAndRefreshSurvey(
                survey.id,
                { start_date: new Date().toISOString() },
                'Survey launched'
            )
            actions.setLifecyclePending(false)
            actions.loadSurveys()
            if (ok) {
                actions.cancelQuickCreate()
            }
        },
        stopSurvey: async ({ survey }) => {
            if (values.isLifecyclePending) {
                return
            }
            actions.setLifecyclePending(true)
            const ok = await patchAndRefreshSurvey(survey.id, { end_date: new Date().toISOString() }, 'Survey ended')
            actions.setLifecyclePending(false)
            actions.loadSurveys()
            if (ok) {
                actions.cancelQuickCreate()
            }
        },
        resumeSurvey: async ({ survey }) => {
            if (values.isLifecyclePending) {
                return
            }
            actions.setLifecyclePending(true)
            const ok = await patchAndRefreshSurvey(survey.id, { end_date: null }, 'Survey resumed')
            actions.setLifecyclePending(false)
            actions.loadSurveys()
            if (ok) {
                actions.cancelQuickCreate()
            }
        },
        archiveSurvey: async ({ survey }) => {
            if (values.isLifecyclePending) {
                return
            }
            actions.setLifecyclePending(true)
            const ok = await patchAndRefreshSurvey(survey.id, { archived: true }, 'Survey archived')
            actions.setLifecyclePending(false)
            actions.loadSurveys()
            if (ok) {
                actions.cancelQuickCreate()
            }
        },
        submitQuickCreate: async ({ launch }) => {
            // Re-entrancy guard: button shows loading, but a fast keyboard
            // accelerator can fire twice before the reducer commits.
            if (values.isSubmitting) {
                return
            }
            const editingId = values.editingSurveyId
            const editingSurvey = values.editingSurvey
            const payload = buildSurveyPayload(values.quickForm, { existing: editingId ? editingSurvey : null })
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
                // If the user cancelled while we were awaiting, drop the result
                // silently — they explicitly threw the work away.
                if (!values.isCreating) {
                    return
                }
                if (!response.ok) {
                    const error = await response.json().catch(() => ({}))
                    lemonToast.error(
                        formatApiError(
                            error,
                            response.status,
                            editingId ? 'Failed to save survey' : 'Failed to create survey'
                        )
                    )
                    actions.submitQuickCreateFailure()
                    return
                }
                const saved = await response.json().catch(() => ({}))
                toolbarPosthogJS.capture(editingId ? 'toolbar survey edited' : 'toolbar survey created', {
                    question_type: values.quickForm.questionType,
                    has_url_targeting: values.quickForm.targetingMode === 'specific',
                    frequency: values.quickForm.frequency,
                    trigger_mode: values.quickForm.triggerMode,
                    launched: launch,
                })
                const { uiHost } = toolbarConfigLogic.values
                const surveyUrl = saved.id ? joinWithUiHost(uiHost, urls.survey(saved.id)) : null
                const message = editingId
                    ? launch
                        ? 'Survey saved and launched'
                        : 'Survey saved'
                    : launch
                      ? 'Survey launched'
                      : 'Draft survey created'
                lemonToast.success(message, {
                    button: surveyUrl
                        ? {
                              label: 'Open in PostHog',
                              action: () => window.open(surveyUrl, '_blank'),
                          }
                        : undefined,
                })
                actions.submitQuickCreateSuccess()
                actions.loadSurveys()
            } catch (e) {
                // eslint-disable-next-line no-console
                console.warn('[Toolbar] survey submit failed', e)
                lemonToast.error(editingId ? 'Failed to save survey' : 'Failed to create survey')
                actions.submitQuickCreateFailure()
            }
        },
    })),
])
