import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { dayjs } from 'lib/dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { addProductIntent } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { EventsNode, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import {
    BasicSurveyQuestion,
    LinkSurveyQuestion,
    RatingSurveyQuestion,
    Survey,
    SurveyQuestion,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import { NewSurvey, SURVEY_CREATED_SOURCE, SURVEY_RATING_SCALE, defaultSurveyAppearance } from '../constants'
import { surveysLogic } from '../surveysLogic'
import { toSurveyEvent } from '../utils/opportunityDetection'
import type { quickSurveyFormLogicType } from './quickSurveyFormLogicType'
import { QuickSurveyType } from './types'

export type QuickSurveyCreateMode = 'launch' | 'edit' | 'draft'
export type QuickSurveyQuestionType = SurveyQuestionType.Open | SurveyQuestionType.Rating | SurveyQuestionType.Link

export const DEFAULT_RATING_LOWER_LABEL = 'Ugh, gross'
export const DEFAULT_RATING_UPPER_LABEL = 'Sparks joy'

export interface QuickSurveyFormValues {
    name: string
    question: string
    description?: string
    questionType: QuickSurveyQuestionType
    scaleType?: 'number' | 'emoji'
    ratingLowerBound?: string
    ratingUpperBound?: string
    buttonText?: string
    link?: string
    conditions: Survey['conditions']
    appearance: Survey['appearance']
    linkedFlagId?: number | null
    followUpQuestion?: string
    followUpEnabled?: boolean
}

export interface QuickSurveyFormLogicProps {
    key: string
    defaults: Partial<QuickSurveyFormValues>
    source: SURVEY_CREATED_SOURCE
    contextType: QuickSurveyType
    onSuccess?: () => void
}

function buildSurveyQuestions(formValues: QuickSurveyFormValues): SurveyQuestion[] {
    const questions = [buildSurveyQuestion(formValues)]

    if (formValues.followUpEnabled && formValues.followUpQuestion?.trim()) {
        questions.push({
            type: SurveyQuestionType.Open,
            question: formValues.followUpQuestion,
            optional: true,
        })
    }

    return questions
}

function buildSurveyQuestion(
    formValues: QuickSurveyFormValues
): BasicSurveyQuestion | RatingSurveyQuestion | LinkSurveyQuestion {
    if (formValues.questionType === SurveyQuestionType.Rating) {
        return {
            type: SurveyQuestionType.Rating,
            question: formValues.question,
            optional: false,
            display: formValues.scaleType || 'emoji',
            scale: SURVEY_RATING_SCALE.LIKERT_5_POINT,
            lowerBoundLabel: formValues.ratingLowerBound || DEFAULT_RATING_LOWER_LABEL,
            upperBoundLabel: formValues.ratingUpperBound || DEFAULT_RATING_UPPER_LABEL,
            skipSubmitButton: true,
        }
    } else if (formValues.questionType === SurveyQuestionType.Link) {
        return {
            type: SurveyQuestionType.Link,
            question: formValues.question,
            description: formValues.description,
            buttonText: formValues.buttonText,
            link: formValues.link ?? null,
            optional: true,
        }
    }
    return {
        type: SurveyQuestionType.Open,
        question: formValues.question,
        optional: false,
    }
}

export const quickSurveyFormLogic = kea<quickSurveyFormLogicType>([
    path(['scenes', 'surveys', 'quickSurveyFormLogic']),
    props({} as QuickSurveyFormLogicProps),
    key((props) => props.key),

    actions({
        setCreateMode: (mode: QuickSurveyCreateMode) => ({ mode }),
        updateConditions: (updates: Partial<Survey['conditions']>) => ({ updates }),
        updateAppearance: (updates: Partial<Survey['appearance']>) => ({ updates }),
        setTriggerEvent: (step: EventsNode | null, field: 'events' | 'cancelEvents') => ({ step, field }),
    }),

    forms(({ props, values }) => ({
        surveyForm: {
            defaults: {
                name: '',
                question: '',
                conditions: {
                    actions: null,
                    events: { values: [] },
                    cancelEvents: { values: [] },
                },
                appearance: defaultSurveyAppearance,
                linkedFlagId: undefined,
                ...props.defaults,
            } as QuickSurveyFormValues,

            errors: ({ question, appearance, buttonText }) => ({
                question: !question?.trim()
                    ? props.contextType === QuickSurveyType.ANNOUNCEMENT
                        ? 'Please enter a title'
                        : 'Please enter a question'
                    : undefined,
                appearance:
                    props.contextType === QuickSurveyType.FUNNEL && !appearance?.surveyPopupDelaySeconds
                        ? { surveyPopupDelaySeconds: 'A delay is required for funnel sequence targeting' as any }
                        : undefined,
                buttonText:
                    props.contextType === QuickSurveyType.ANNOUNCEMENT && !buttonText
                        ? 'Please enter your button text'
                        : undefined,
            }),

            submit: async (formValues) => {
                const shouldLaunch = values.createMode === 'launch'
                const shouldEdit = values.createMode === 'edit'

                const surveyData: Partial<Survey> = {
                    name: formValues.name,
                    type: SurveyType.Popover,
                    questions: buildSurveyQuestions(formValues),
                    conditions: formValues.conditions,
                    appearance: formValues.appearance,
                    ...(formValues.linkedFlagId ? { linked_flag_id: formValues.linkedFlagId } : {}),
                    ...(shouldLaunch ? { start_date: dayjs().toISOString() } : {}),
                }

                const response = await api.surveys.create(surveyData)

                eventUsageLogic.actions.reportSurveyCreated(response)
                addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_CREATED,
                    metadata: {
                        survey_id: response.id,
                        source: props.source,
                        created_successfully: true,
                        quick_survey: true,
                        create_mode: values.createMode,
                    },
                })

                lemonToast.success(shouldLaunch ? 'Survey created and launched!' : 'Survey created as draft')
                router.actions.push(`${urls.survey(response.id)}${shouldEdit ? '?edit=true' : ''}`)

                props.onSuccess?.()
                surveysLogic.actions.loadSurveys()

                // Keep track of the tasks that were completed for our onboarding depending on the create mode
                const completedTasks = [
                    SetupTaskId.CreateSurvey,
                    shouldLaunch ? SetupTaskId.LaunchSurvey : undefined,
                ].filter(Boolean) as SetupTaskId[]
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(completedTasks)
            },
        },
    })),

    reducers({
        createMode: [
            'launch' as QuickSurveyCreateMode,
            {
                setCreateMode: (_, { mode }) => mode,
            },
        ],
    }),

    selectors({
        selectedEvents: [
            (s) => [s.surveyForm],
            (surveyForm): string[] =>
                (surveyForm.conditions?.events?.values || []).map((e: { name: string }) => e.name),
        ],
        cancelEvents: [
            (s) => [s.surveyForm],
            (surveyForm): string[] =>
                (surveyForm.conditions?.cancelEvents?.values || []).map((e: { name: string }) => e.name),
        ],
        delaySeconds: [
            (s) => [s.surveyForm],
            (surveyForm): number => surveyForm.appearance?.surveyPopupDelaySeconds ?? 15,
        ],
        previewSurvey: [
            (s) => [s.surveyForm],
            (surveyForm): NewSurvey =>
                ({
                    id: 'new',
                    name: surveyForm.name,
                    type: SurveyType.Popover,
                    questions: buildSurveyQuestions(surveyForm),
                    conditions: surveyForm.conditions,
                    appearance: surveyForm.appearance,
                }) as NewSurvey,
        ],
        submitDisabledReason: [
            (s) => [s.surveyFormErrors],
            (errors: Record<string, string | undefined>): string | undefined => {
                return Object.values(errors).find(Boolean) as string | undefined
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setCreateMode: () => {
            actions.submitSurveyForm()
        },
        updateConditions: ({ updates }) => {
            actions.setSurveyFormValue('conditions', {
                ...values.surveyForm.conditions,
                ...updates,
            })
        },
        updateAppearance: ({ updates }) => {
            actions.setSurveyFormValue('appearance', {
                ...values.surveyForm.appearance,
                ...updates,
            })
        },
        setTriggerEvent: ({ step, field }) => {
            const event = step ? toSurveyEvent(step) : null
            actions.updateConditions({
                [field]: {
                    values: event ? [event] : [],
                },
            })
        },
        submitSurveyFormSuccess: () => {},
    })),
])
