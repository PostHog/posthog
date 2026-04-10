import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { DESTINATION_OPTIONS, DestinationKey } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import {
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
    HOG_FUNCTION_SUB_TEMPLATES,
} from 'scenes/hog-functions/sub-templates/sub-templates'
import { NEW_SURVEY } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyNotificationFilters, getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

import { HogFunctionTemplateType, HogFunctionType, IntegrationType, Survey, SurveyQuestionType } from '~/types'

import type { surveyNotificationModalLogicType } from './surveyNotificationModalLogicType'

export const WEBHOOK_METHOD_OPTIONS = [
    { value: 'POST', label: 'POST' },
    { value: 'PUT', label: 'PUT' },
    { value: 'PATCH', label: 'PATCH' },
    { value: 'GET', label: 'GET' },
    { value: 'DELETE', label: 'DELETE' },
]

export type SurveyQuestionForNotification = {
    id?: string
    question: string | null | undefined
    type: SurveyQuestionType
}

export interface SurveyNotificationForm {
    destination: DestinationKey
    onlyCompletedResponses: boolean
    slackIntegrationId: number | null
    slackChannel: string | null
    slackMessage: string
    includeSlackButtons: boolean
    discordWebhookUrl: string
    discordMessage: string
    teamsWebhookUrl: string
    teamsMessage: string
    webhookUrl: string
    webhookMethod: string
    webhookBody: string
}

export interface SurveyNotificationModalLogicProps {
    surveyId: string
}

type SurveyMessageField = 'slackMessage' | 'discordMessage' | 'teamsMessage'
type SurveyNotificationContext = Pick<Survey, 'id' | 'name' | 'questions' | 'enable_partial_responses'>
type SurveyNotificationFormErrors = Partial<Record<keyof SurveyNotificationForm, string>>

const MAX_EXAMPLE_QUESTIONS = 3
export const SURVEY_NAME_TOKEN = "{event.properties['$survey_name']}"
export const SURVEY_ID_TOKEN = "{event.properties['$survey_id']}"
export const RESPONDENT_NAME_TOKEN = '{person.name}'
export const RESPONDENT_EMAIL_TOKEN = '{person.properties.email}'
export const RESPONDENT_DETAILS_LINE = `${RESPONDENT_NAME_TOKEN} · ${RESPONDENT_EMAIL_TOKEN}`

function getResponseToken(questionId: string): string {
    return `{event.properties['${getSurveyIdBasedResponseKey(questionId)}']}`
}

export function getQuestionLabel(question: SurveyQuestionForNotification, index: number): string {
    return question.question?.trim() || `Question ${index + 1}`
}

function getQuestionLine(question: SurveyQuestionForNotification, index: number): string {
    return `- ${getQuestionLabel(question, index)}: ${getResponseToken(question.id!)}`
}

export function getDefaultSurveyMessage(questions: SurveyQuestionForNotification[] = []): string {
    const exampleQuestions = questions
        .filter((question) => question.id && question.type !== SurveyQuestionType.Link)
        .slice(0, MAX_EXAMPLE_QUESTIONS)

    return [
        `*New response on ${SURVEY_NAME_TOKEN}*`,
        RESPONDENT_DETAILS_LINE,
        ...(exampleQuestions.length > 0
            ? ['', '*Responses*', ...exampleQuestions.map((question, index) => getQuestionLine(question, index))]
            : []),
    ].join('\n')
}

export function appendQuestionToken(value: string, question: SurveyQuestionForNotification, index: number): string {
    if (!question.id) {
        return value
    }

    const line = getQuestionLine(question, index)
    const trimmedValue = value.trim()

    if (trimmedValue.includes(line)) {
        return trimmedValue
    }

    if (!trimmedValue) {
        return getDefaultSurveyMessage([question])
    }

    if (trimmedValue.includes('*Responses*')) {
        return `${trimmedValue}\n${line}`
    }

    return `${trimmedValue}\n\n*Responses*\n${line}`
}

export function appendTemplateLine(value: string, line: string): string {
    const trimmedValue = value.trim()

    if (trimmedValue.includes(line)) {
        return trimmedValue
    }

    return trimmedValue ? `${trimmedValue}\n${line}` : line
}

function isValidHttpUrl(value: string): boolean {
    return URL.canParse(value) && /^https?:\/\//.test(value)
}

function buildSlackBlocks(message: string, includeButtons: boolean): Record<string, unknown>[] {
    return [
        {
            type: 'section',
            text: {
                type: 'mrkdwn',
                text: message,
            },
        },
        ...(includeButtons
            ? [
                  {
                      type: 'actions',
                      elements: [
                          {
                              url: "{project.url}/surveys/{event.properties['$survey_id']}",
                              text: { text: 'View survey', type: 'plain_text' },
                              type: 'button',
                          },
                          {
                              url: '{person.url}',
                              text: { text: 'View person', type: 'plain_text' },
                              type: 'button',
                          },
                      ],
                  },
              ]
            : []),
    ]
}

function buildWebhookBodyTemplate(questions: SurveyQuestionForNotification[]): Record<string, unknown> {
    return {
        survey: {
            id: SURVEY_ID_TOKEN,
            name: SURVEY_NAME_TOKEN,
            url: `{project.url}/surveys/${SURVEY_ID_TOKEN}`,
        },
        person: {
            name: RESPONDENT_NAME_TOKEN,
            email: RESPONDENT_EMAIL_TOKEN,
            url: '{person.url}',
        },
        responses: questions
            .filter((question) => question.id && question.type !== SurveyQuestionType.Link)
            .map((question, index) => ({
                question: getQuestionLabel(question, index),
                answer: getResponseToken(question.id!),
            })),
    }
}

function buildSurveyNotificationForm(survey: SurveyNotificationContext): SurveyNotificationForm {
    const defaultMessage = getDefaultSurveyMessage(survey.questions)

    return {
        destination: 'slack',
        onlyCompletedResponses: true,
        slackIntegrationId: null,
        slackChannel: null,
        slackMessage: defaultMessage,
        includeSlackButtons: true,
        discordWebhookUrl: '',
        discordMessage: defaultMessage,
        teamsWebhookUrl: '',
        teamsMessage: defaultMessage,
        webhookUrl: '',
        webhookMethod: 'POST',
        webhookBody: JSON.stringify(buildWebhookBodyTemplate(survey.questions), null, 2),
    }
}

function buildTemplateGlobals(survey: SurveyNotificationContext): Record<string, unknown> {
    const responseProperties = Object.fromEntries(
        survey.questions
            .filter((question) => question.id && question.type !== SurveyQuestionType.Link)
            .map((question, index) => [
                getSurveyIdBasedResponseKey(question.id!),
                question.question || `Example answer ${index + 1}`,
            ])
    )
    const previewTimestamp = new Date().toISOString()

    return {
        project: {
            id: 1,
            name: 'Project',
            url: 'https://app.posthog.com/project/1',
        },
        event: {
            event: 'survey sent',
            uuid: '00000000-0000-0000-0000-000000000000',
            distinct_id: 'example-distinct-id',
            timestamp: previewTimestamp,
            properties: {
                $survey_id: survey.id === NEW_SURVEY.id ? 'survey-id' : survey.id,
                $survey_name: survey.name || 'Survey',
                $survey_completed: true,
                ...responseProperties,
            },
            url: `https://app.posthog.com/project/1/events/example/${encodeURIComponent(previewTimestamp)}`,
        },
        person: {
            id: 'person-id',
            name: 'Jane Doe',
            url: 'https://app.posthog.com/project/1/person/example-distinct-id',
            properties: {
                email: 'jane@example.com',
            },
        },
        groups: {},
    }
}

function notificationNameFor(destination: DestinationKey, surveyName?: string | null): string {
    const destinationLabel = DESTINATION_OPTIONS.find((option) => option.value === destination)?.label || 'Notification'
    const baseName = surveyName?.trim() || 'Survey'
    return `${baseName} → ${destinationLabel}`
}

export function destinationDeliveryDescription(destination: DestinationKey): string {
    switch (destination) {
        case 'slack':
            return 'Slack messages are sent as a formatted post with buttons to view the survey and person.'
        case 'discord':
            return 'Discord sends a single message to your webhook URL using the content below.'
        case 'microsoft-teams':
            return 'Microsoft Teams sends an Adaptive Card message using the text below.'
        case 'webhook':
            return 'Webhooks send a JSON request. You can tailor the method and request body here.'
    }
}

function createSurveyNotificationPayload({
    template,
    destination,
    surveyName,
    surveyId,
    canNotifyOnPartialResponses,
    form,
}: {
    template: HogFunctionTemplateType
    destination: DestinationKey
    surveyName?: string | null
    surveyId: string
    canNotifyOnPartialResponses: boolean
    form: SurveyNotificationForm
}): Partial<HogFunctionType> {
    const destinationOption = DESTINATION_OPTIONS.find((option) => option.value === destination)
    if (!destinationOption) {
        throw new Error('Unsupported destination')
    }

    const subTemplate = HOG_FUNCTION_SUB_TEMPLATES['survey-response'].find(
        (subTemplateValue) => subTemplateValue.template_id === destinationOption.templateId
    )

    const inputs: Record<string, { value: unknown }> = {}

    for (const schema of template.inputs_schema ?? []) {
        if (schema.default !== undefined) {
            inputs[schema.key] = { value: schema.default }
        }
    }

    if (subTemplate?.inputs) {
        for (const [key, value] of Object.entries(subTemplate.inputs)) {
            inputs[key] = value as { value: unknown }
        }
    }

    switch (destination) {
        case 'slack':
            if (!form.slackIntegrationId || !form.slackChannel) {
                throw new Error('Select a Slack workspace and channel.')
            }
            inputs.slack_workspace = { value: form.slackIntegrationId }
            inputs.channel = { value: form.slackChannel.split('|')[0] }
            inputs.text = { value: form.slackMessage.trim() }
            inputs.blocks = { value: buildSlackBlocks(form.slackMessage.trim(), form.includeSlackButtons) }
            break
        case 'discord':
            inputs.webhookUrl = { value: form.discordWebhookUrl.trim() }
            inputs.content = { value: form.discordMessage.trim() }
            break
        case 'microsoft-teams':
            inputs.webhookUrl = { value: form.teamsWebhookUrl.trim() }
            inputs.text = { value: form.teamsMessage.trim() }
            break
        case 'webhook':
            inputs.url = { value: form.webhookUrl.trim() }
            inputs.method = { value: form.webhookMethod }
            inputs.body = { value: JSON.parse(form.webhookBody) }
            break
    }

    return {
        template_id: destinationOption.templateId,
        type: HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'].type,
        name: notificationNameFor(destination, surveyName),
        description: subTemplate?.description ?? `Survey notification for ${destinationOption.label}`,
        inputs,
        inputs_schema: template.inputs_schema,
        filters: getSurveyNotificationFilters(
            surveyId,
            canNotifyOnPartialResponses ? form.onlyCompletedResponses : true
        ),
        hog: template.code,
        icon_url: template.icon_url,
        enabled: true,
    }
}

function getNotificationFormErrors(
    form: SurveyNotificationForm,
    survey: SurveyNotificationContext,
    hasSlackIntegration: boolean
): SurveyNotificationFormErrors {
    if (survey.id === NEW_SURVEY.id) {
        return {}
    }

    switch (form.destination) {
        case 'slack':
            return {
                slackIntegrationId: !hasSlackIntegration
                    ? 'Configure Slack for this project first.'
                    : !form.slackIntegrationId
                      ? 'Select a Slack workspace.'
                      : undefined,
                slackChannel: form.slackIntegrationId && !form.slackChannel ? 'Select a Slack channel.' : undefined,
                slackMessage: !form.slackMessage.trim() ? 'Enter the Slack message.' : undefined,
            }
        case 'discord':
            return {
                discordWebhookUrl: !isValidHttpUrl(form.discordWebhookUrl.trim())
                    ? 'Enter a valid Discord webhook URL.'
                    : undefined,
                discordMessage: !form.discordMessage.trim() ? 'Enter the Discord message.' : undefined,
            }
        case 'microsoft-teams':
            return {
                teamsWebhookUrl: !isValidHttpUrl(form.teamsWebhookUrl.trim())
                    ? 'Enter a valid Microsoft Teams webhook URL.'
                    : undefined,
                teamsMessage: !form.teamsMessage.trim() ? 'Enter the Microsoft Teams message.' : undefined,
            }
        case 'webhook':
            try {
                if (!isValidHttpUrl(form.webhookUrl.trim())) {
                    return { webhookUrl: 'Enter a valid webhook URL.' }
                }
                if (!form.webhookBody.trim()) {
                    return { webhookBody: 'Enter valid JSON for the webhook body.' }
                }
                JSON.parse(form.webhookBody)
                return {}
            } catch {
                return { webhookBody: 'Enter valid JSON for the webhook body.' }
            }
    }
}

export const surveyNotificationModalLogic = kea<surveyNotificationModalLogicType>([
    path(['scenes', 'surveys', 'surveyNotificationModalLogic']),
    props({} as SurveyNotificationModalLogicProps),
    key((props) => props.surveyId),
    connect((props: SurveyNotificationModalLogicProps) => ({
        values: [integrationsLogic, ['integrations'], surveyLogic({ id: props.surveyId }), ['survey']],
        actions: [surveyLogic({ id: props.surveyId }), ['loadSurveyNotifications']],
    })),

    actions({
        openDialog: true,
        closeDialog: true,
        setNotificationSubmissionError: (error: string | null) => ({ error }),
    }),

    reducers({
        isOpen: [
            false,
            {
                openDialog: () => true,
                closeDialog: () => false,
            },
        ],
        notificationSubmissionError: [
            null as string | null,
            {
                setNotificationSubmissionError: (_, { error }) => error,
                openDialog: () => null,
                closeDialog: () => null,
            },
        ],
    }),

    forms(({ values }) => ({
        notificationForm: {
            defaults: buildSurveyNotificationForm(NEW_SURVEY),
            errors: (form: SurveyNotificationForm) =>
                getNotificationFormErrors(
                    form,
                    values.survey,
                    (values.integrations?.some((integration: IntegrationType) => integration.kind === 'slack') ??
                        false) as boolean
                ),
            submit: async (form: SurveyNotificationForm) => {
                const templateId = DESTINATION_OPTIONS.find((option) => option.value === form.destination)?.templateId
                const template = await api.hogFunctions.getTemplate(templateId || 'template-slack')

                const payload = createSurveyNotificationPayload({
                    template,
                    destination: form.destination,
                    surveyName: values.survey.name,
                    surveyId: values.survey.id,
                    canNotifyOnPartialResponses: values.survey.enable_partial_responses === true,
                    form,
                })

                await api.hogFunctions.create(payload)
            },
        },
    })),

    selectors({
        hasSlackIntegration: [
            (s) => [s.integrations],
            (integrations: IntegrationType[] | null) =>
                integrations?.some((integration: IntegrationType) => integration.kind === 'slack') ?? false,
        ],
        selectedSlackIntegration: [
            (s) => [s.integrations, s.notificationForm],
            (integrations: IntegrationType[] | null, form: SurveyNotificationForm) =>
                integrations?.find((integration: IntegrationType) => integration.id === form.slackIntegrationId) ??
                null,
        ],
        canNotifyOnPartialResponses: [
            (s) => [s.survey],
            (survey: SurveyNotificationContext) => survey.enable_partial_responses === true,
        ],
        templateGlobals: [(s) => [s.survey], (survey: SurveyNotificationContext) => buildTemplateGlobals(survey)],
        submitDisabledReason: [
            (s) => [s.survey, s.notificationFormErrors, s.isNotificationFormSubmitting],
            (
                survey: SurveyNotificationContext,
                errors: SurveyNotificationFormErrors,
                isSubmitting: boolean
            ): string | undefined => {
                if (survey.id === NEW_SURVEY.id) {
                    return 'Save the survey before creating notifications.'
                }
                if (isSubmitting) {
                    return 'Creating notification...'
                }
                return (Object.values(errors).find(Boolean) as string | undefined) ?? undefined
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openDialog: () => {
            actions.resetNotificationForm()
            actions.setNotificationFormValues(buildSurveyNotificationForm(values.survey))
            if (values.survey.enable_partial_responses !== true) {
                actions.setNotificationFormValue('onlyCompletedResponses', true)
            }
        },
        closeDialog: () => {
            actions.resetNotificationForm()
        },
        submitNotificationFormSuccess: async () => {
            await actions.loadSurveyNotifications()
            actions.closeDialog()
            lemonToast.success(
                `Notification "${notificationNameFor(values.notificationForm.destination, values.survey.name)}" created`
            )
        },
        submitNotificationFormFailure: ({ error }) => {
            actions.setNotificationSubmissionError(
                error instanceof Error ? error.message : 'Failed to create notification. Please try again.'
            )
        },
    })),
])

export function getMessageFieldForDestination(destination: DestinationKey): SurveyMessageField | null {
    switch (destination) {
        case 'slack':
            return 'slackMessage'
        case 'discord':
            return 'discordMessage'
        case 'microsoft-teams':
            return 'teamsMessage'
        case 'webhook':
            return null
    }
}
