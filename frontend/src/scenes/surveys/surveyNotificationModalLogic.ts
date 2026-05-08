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
import {
    buildSurveyExampleInvocationGlobals,
    getSurveyNotificationFilters,
    getSurveyIdBasedResponseKey,
} from 'scenes/surveys/utils'

import {
    HogFunctionTemplateType,
    HogFunctionType,
    IntegrationType,
    Survey,
    SurveyEventProperties,
    SurveyQuestionType,
} from '~/types'

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
type HogFunctionInputValue = HogFunctionType['inputs'] extends Record<string, infer T> | null | undefined ? T : never
export type SurveyNotificationModalIntent = 'add' | 'edit' | 'copy'
export type OpenSurveyNotificationDialogPayload = {
    notification?: HogFunctionType | null
    intent?: SurveyNotificationModalIntent
}
type SurveyNotificationContext = Pick<Survey, 'id' | 'name' | 'questions' | 'enable_partial_responses'>
type SurveyNotificationFormErrors = Partial<Record<keyof SurveyNotificationForm, string>>

const MAX_EXAMPLE_QUESTIONS = 3
export const SURVEY_NAME_TOKEN = "{event.properties['$survey_name']}"
export const SURVEY_ID_TOKEN = "{event.properties['$survey_id']}"
export const SURVEY_EVENT_TOKEN = '{event.event}'
export const RESPONDENT_NAME_TOKEN = '{person.name}'
export const RESPONDENT_EMAIL_TOKEN = '{person.properties.email}'
export const RESPONDENT_DETAILS_LINE = `${RESPONDENT_NAME_TOKEN} · ${RESPONDENT_EMAIL_TOKEN}`
export const SURVEY_STATUS_TOKEN = `{event.event == 'survey dismissed' ? (event.properties['${SurveyEventProperties.SURVEY_PARTIALLY_COMPLETED}'] ? 'Dismissed after a partial response' : 'Dismissed before completion') : 'Completed response'}`

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
        `*Survey update on ${SURVEY_NAME_TOKEN}*`,
        SURVEY_STATUS_TOKEN,
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
        event: {
            name: SURVEY_EVENT_TOKEN,
            status: SURVEY_STATUS_TOKEN,
        },
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
    return buildSurveyExampleInvocationGlobals({
        survey,
        projectId: 1,
        projectName: 'Project',
        projectUrl: 'https://app.posthog.com/project/1',
    })
}

function notificationNameFor(destination: DestinationKey, surveyName?: string | null): string {
    const destinationLabel = DESTINATION_OPTIONS.find((option) => option.value === destination)?.label || 'Notification'
    const baseName = surveyName?.trim() || 'Survey'
    return `${baseName} → ${destinationLabel}`
}

function getSurveyResponseKeysInOrder(value: unknown): string[] {
    const keys: string[] = []
    const seenKeys = new Set<string>()

    const collectKeys = (candidate: unknown): void => {
        if (typeof candidate === 'string') {
            const responseKeyRegex = /\$survey_response_[^'"\]\s,}:]+/g
            for (const match of candidate.matchAll(responseKeyRegex)) {
                const key = match[0]
                if (!seenKeys.has(key)) {
                    seenKeys.add(key)
                    keys.push(key)
                }
            }
            return
        }

        if (Array.isArray(candidate)) {
            candidate.forEach(collectKeys)
            return
        }

        if (candidate && typeof candidate === 'object') {
            for (const [key, nestedValue] of Object.entries(candidate)) {
                collectKeys(key)
                collectKeys(nestedValue)
            }
        }
    }

    collectKeys(value)
    return keys
}

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function replaceSurveyResponseKeys(
    value: string,
    responseKeyMap: Map<string, string>,
    unmappedResponseKeys: Set<string>
): string {
    let nextValue = value
    for (const [sourceKey, targetKey] of responseKeyMap) {
        nextValue = nextValue.replaceAll(sourceKey, targetKey)
    }
    for (const sourceKey of unmappedResponseKeys) {
        nextValue = nextValue.replace(
            new RegExp(`\\{event\\.properties\\[['"]${escapeRegExp(sourceKey)}['"]\\]\\}`, 'g'),
            ''
        )
        nextValue = nextValue.replaceAll(sourceKey, '')
    }
    return nextValue
}

export function remapSurveyResponseProperties<T>(value: T, survey: SurveyNotificationContext): T {
    const targetResponseKeys = survey.questions
        .filter((question) => question.id && question.type !== SurveyQuestionType.Link)
        .map((question) => getSurveyIdBasedResponseKey(question.id!))
    const sourceResponseKeys = getSurveyResponseKeysInOrder(value)
    const responseKeyMap = new Map<string, string>()
    const unmappedResponseKeys = new Set<string>()

    sourceResponseKeys.forEach((sourceKey, index) => {
        const targetKey = targetResponseKeys[index]
        if (targetKey) {
            responseKeyMap.set(sourceKey, targetKey)
        } else {
            unmappedResponseKeys.add(sourceKey)
        }
    })

    const remapValue = (candidate: unknown): unknown => {
        if (typeof candidate === 'string') {
            return replaceSurveyResponseKeys(candidate, responseKeyMap, unmappedResponseKeys)
        }

        if (Array.isArray(candidate)) {
            return candidate.map(remapValue)
        }

        if (candidate && typeof candidate === 'object') {
            const remappedEntries: [string, unknown][] = []
            for (const [key, nestedValue] of Object.entries(candidate)) {
                const remappedKey = replaceSurveyResponseKeys(key, responseKeyMap, unmappedResponseKeys)
                if (remappedKey) {
                    remappedEntries.push([remappedKey, remapValue(nestedValue)])
                }
            }
            return Object.fromEntries(remappedEntries)
        }

        return candidate
    }

    return remapValue(value) as T
}

function getInputValue(inputs: HogFunctionType['inputs'], key: string): unknown {
    return inputs?.[key]?.value
}

function getInputString(inputs: HogFunctionType['inputs'], key: string): string {
    const value = getInputValue(inputs, key)
    return typeof value === 'string' ? value : ''
}

function getInputNumber(inputs: HogFunctionType['inputs'], key: string): number | null {
    const value = getInputValue(inputs, key)
    return typeof value === 'number' ? value : null
}

function getDestinationForNotification(notification: HogFunctionType): DestinationKey {
    const templateId = notification.template_id || notification.template?.id
    return DESTINATION_OPTIONS.find((option) => option.templateId === templateId)?.value ?? 'webhook'
}

function getSlackMessageFromNotification(notification: HogFunctionType, defaultMessage: string): string {
    const text = getInputString(notification.inputs, 'text')
    if (text) {
        return text
    }

    const blocks = getInputValue(notification.inputs, 'blocks')
    if (!Array.isArray(blocks)) {
        return defaultMessage
    }

    const section = blocks.find((block): block is { text?: { text?: unknown } } => {
        return (
            typeof block === 'object' &&
            block !== null &&
            'type' in block &&
            (block as { type?: unknown }).type === 'section'
        )
    })
    const sectionText = section?.text?.text
    return typeof sectionText === 'string' ? sectionText : defaultMessage
}

function getSlackIncludeButtons(notification: HogFunctionType): boolean {
    const blocks = getInputValue(notification.inputs, 'blocks')
    return Array.isArray(blocks)
        ? blocks.some((block) => {
              return (
                  typeof block === 'object' &&
                  block !== null &&
                  'type' in block &&
                  (block as { type?: unknown }).type === 'actions'
              )
          })
        : false
}

function buildSurveyNotificationFormFromNotification(
    notification: HogFunctionType,
    survey: SurveyNotificationContext,
    remapResponses: boolean
): SurveyNotificationForm {
    const defaults = buildSurveyNotificationForm(survey)
    const destination = getDestinationForNotification(notification)
    const remappedInputs = remapResponses
        ? remapSurveyResponseProperties(notification.inputs, survey)
        : notification.inputs
    const remappedNotification = { ...notification, inputs: remappedInputs }

    return {
        ...defaults,
        destination,
        slackIntegrationId: getInputNumber(remappedInputs, 'slack_workspace'),
        slackChannel: getInputString(remappedInputs, 'channel') || null,
        slackMessage: getSlackMessageFromNotification(remappedNotification, defaults.slackMessage),
        includeSlackButtons: getSlackIncludeButtons(remappedNotification),
        discordWebhookUrl: getInputString(remappedInputs, 'webhookUrl'),
        discordMessage: getInputString(remappedInputs, 'content') || defaults.discordMessage,
        teamsWebhookUrl: getInputString(remappedInputs, 'webhookUrl'),
        teamsMessage: getInputString(remappedInputs, 'text') || defaults.teamsMessage,
        webhookUrl: getInputString(remappedInputs, 'url'),
        webhookMethod: getInputString(remappedInputs, 'method') || defaults.webhookMethod,
        webhookBody: JSON.stringify(
            getInputValue(remappedInputs, 'body') ?? buildWebhookBodyTemplate(survey.questions),
            null,
            2
        ),
    }
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
    form,
}: {
    template: HogFunctionTemplateType
    destination: DestinationKey
    surveyName?: string | null
    surveyId: string
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
        filters: getSurveyNotificationFilters(surveyId),
        hog: template.code,
        icon_url: template.icon_url,
        enabled: true,
    }
}

function updateSurveyNotificationPayload({
    notification,
    template,
    destination,
    surveyId,
    form,
}: {
    notification: HogFunctionType
    template: HogFunctionTemplateType
    destination: DestinationKey
    surveyId: string
    form: SurveyNotificationForm
}): Partial<HogFunctionType> {
    const payload = createSurveyNotificationPayload({
        template,
        destination,
        surveyName: null,
        surveyId,
        form,
    })

    return {
        template_id: notification.template_id ?? notification.template?.id ?? payload.template_id,
        type: notification.type,
        name: notification.name,
        description: notification.description,
        inputs_schema: notification.inputs_schema ?? payload.inputs_schema,
        enabled: notification.enabled,
        inputs: {
            ...notification.inputs,
            ...(payload.inputs as Record<string, HogFunctionInputValue>),
        },
        mappings: notification.mappings,
        masking: notification.masking,
        filters: notification.filters ?? payload.filters,
        hog: notification.hog ?? payload.hog,
        icon_url: notification.icon_url ?? payload.icon_url,
    }
}

function getSurveyNotificationDestinationLabel(notification: HogFunctionType): string {
    const templateId = notification.template_id ?? notification.template?.id
    return DESTINATION_OPTIONS.find((option) => option.templateId === templateId)?.label ?? 'Notification'
}

function createCopiedSurveyNotificationPayload({
    notification,
    template,
    destination,
    survey,
    form,
}: {
    notification: HogFunctionType
    template: HogFunctionTemplateType
    destination: DestinationKey
    survey: SurveyNotificationContext
    form: SurveyNotificationForm
}): Partial<HogFunctionType> {
    const payload = createSurveyNotificationPayload({
        template,
        destination,
        surveyName: survey.name,
        surveyId: survey.id,
        form,
    })

    return {
        template_id: notification.template_id ?? notification.template?.id,
        type: notification.type,
        name: notificationNameFor(destination, survey.name),
        description:
            notification.description ||
            `Survey notification for ${getSurveyNotificationDestinationLabel(notification)}`,
        inputs_schema: notification.inputs_schema ?? template.inputs_schema,
        inputs: {
            ...(remapSurveyResponseProperties(notification.inputs ?? {}, survey) as Record<
                string,
                HogFunctionInputValue
            >),
            ...(payload.inputs as Record<string, HogFunctionInputValue>),
        },
        mappings: remapSurveyResponseProperties(notification.mappings, survey),
        masking: notification.masking,
        filters: getSurveyNotificationFilters(survey.id),
        hog: remapSurveyResponseProperties(notification.hog, survey) ?? template.code,
        icon_url: notification.icon_url ?? template.icon_url,
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
        openDialog: (payload: OpenSurveyNotificationDialogPayload = {}) => ({
            notification: payload.notification ?? null,
            intent: payload.intent ?? 'add',
        }),
        closeDialog: true,
        setNotificationSubmissionError: (error: string | null) => ({ error }),
    }),

    reducers({
        editingNotification: [
            null as HogFunctionType | null,
            {
                openDialog: (_, { notification, intent }) => (intent === 'edit' ? notification : null),
                closeDialog: () => null,
            },
        ],
        copiedNotification: [
            null as HogFunctionType | null,
            {
                openDialog: (_, { notification, intent }) => (intent === 'copy' ? notification : null),
                closeDialog: () => null,
            },
        ],
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

                const payload = values.editingNotification
                    ? updateSurveyNotificationPayload({
                          notification: values.editingNotification,
                          template,
                          destination: form.destination,
                          surveyId: values.survey.id,
                          form,
                      })
                    : values.copiedNotification
                      ? createCopiedSurveyNotificationPayload({
                            notification: values.copiedNotification,
                            template,
                            destination: form.destination,
                            survey: values.survey,
                            form,
                        })
                      : createSurveyNotificationPayload({
                            template,
                            destination: form.destination,
                            surveyName: values.survey.name,
                            surveyId: values.survey.id,
                            form,
                        })

                if (values.editingNotification) {
                    await api.hogFunctions.update(values.editingNotification.id, payload)
                } else {
                    await api.hogFunctions.create(payload)
                }
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
        templateGlobals: [(s) => [s.survey], (survey: SurveyNotificationContext) => buildTemplateGlobals(survey)],
        submitDisabledReason: [
            (s) => [
                s.survey,
                s.notificationFormErrors,
                s.isNotificationFormSubmitting,
                s.editingNotification,
                s.copiedNotification,
            ],
            (
                survey: SurveyNotificationContext,
                errors: SurveyNotificationFormErrors,
                isSubmitting: boolean,
                editingNotification: HogFunctionType | null,
                copiedNotification: HogFunctionType | null
            ): string | undefined => {
                if (survey.id === NEW_SURVEY.id) {
                    return 'Save the survey before creating notifications.'
                }
                if (isSubmitting) {
                    return editingNotification
                        ? 'Updating notification...'
                        : copiedNotification
                          ? 'Copying notification...'
                          : 'Creating notification...'
                }
                return (Object.values(errors).find(Boolean) as string | undefined) ?? undefined
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openDialog: ({ notification, intent }) => {
            actions.resetNotificationForm()
            actions.setNotificationFormValues(
                notification
                    ? buildSurveyNotificationFormFromNotification(notification, values.survey, intent === 'copy')
                    : buildSurveyNotificationForm(values.survey)
            )
        },
        closeDialog: () => {
            actions.resetNotificationForm()
        },
        submitNotificationFormSuccess: async () => {
            const updatedNotification = values.editingNotification
            const copiedNotification = values.copiedNotification
            await actions.loadSurveyNotifications()
            actions.closeDialog()
            lemonToast.success(
                updatedNotification
                    ? `Notification "${updatedNotification.name}" updated`
                    : copiedNotification
                      ? `Notification "${notificationNameFor(values.notificationForm.destination, values.survey.name)}" copied`
                      : `Notification "${notificationNameFor(values.notificationForm.destination, values.survey.name)}" created`
            )
        },
        submitNotificationFormFailure: ({ error }) => {
            const action = values.editingNotification ? 'update' : values.copiedNotification ? 'copy' : 'create'
            actions.setNotificationSubmissionError(
                error instanceof Error ? error.message : `Failed to ${action} notification. Please try again.`
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
