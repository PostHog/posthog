import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { convertToHogFunctionInvocationGlobals } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { DESTINATION_OPTIONS, DestinationKey } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import {
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
    HOG_FUNCTION_SUB_TEMPLATES,
} from 'scenes/hog-functions/sub-templates/sub-templates'
import { NEW_SURVEY } from 'scenes/surveys/constants'
import {
    SurveyResponseFilter,
    buildResponseFilterProperties,
    parseResponseFiltersFromProperties,
    stripResponseFiltersFromProperties,
} from 'scenes/surveys/responseFilters'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import {
    buildSurveyExampleInvocationGlobals,
    getSurveyNotificationFilters,
    getSurveyIdBasedResponseKey,
} from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    CyclotronJobInvocationGlobals,
    CyclotronJobTestInvocationResult,
    EventPropertyFilter,
    EventType,
    HogFunctionTemplateType,
    HogFunctionType,
    IntegrationType,
    PersonType,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyEventName,
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
    responseFilters: SurveyResponseFilter[]
}

export interface SurveyNotificationModalLogicProps {
    surveyId: string
}

type SurveyMessageField = 'slackMessage' | 'discordMessage' | 'teamsMessage'
type HogFunctionInputValue = HogFunctionType['inputs'] extends Record<string, infer T> | null | undefined ? T : never
export type SurveyNotificationTestSource = 'sample' | 'last_response'
export type SurveyNotificationModalIntent = 'add' | 'edit' | 'copy'
export type OpenSurveyNotificationDialogPayload = {
    notification?: HogFunctionType | null
    intent?: SurveyNotificationModalIntent
}
type SurveyNotificationContext = Pick<Survey, 'id' | 'name' | 'questions' | 'enable_partial_responses'>
type SurveyNotificationFormErrors = Partial<Record<Exclude<keyof SurveyNotificationForm, 'responseFilters'>, string>>

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
        responseFilters: [],
    }
}

function buildTemplateGlobals(survey: SurveyNotificationContext): CyclotronJobInvocationGlobals {
    return buildSurveyExampleInvocationGlobals({
        survey,
        projectId: 1,
        projectName: 'Project',
        projectUrl: 'https://app.posthog.com/project/1',
    })
}

export function buildLastSurveyResponseQuery(surveyId: string): EventsQuery | null {
    if (!surveyId || surveyId === NEW_SURVEY.id) {
        return null
    }
    return {
        kind: NodeKind.EventsQuery,
        select: ['*', 'person'],
        fixedProperties: [
            {
                key: SurveyEventProperties.SURVEY_ID,
                type: PropertyFilterType.Event,
                value: surveyId,
                operator: PropertyOperator.Exact,
            },
            {
                type: PropertyFilterType.HogQL,
                key: `event IN ('${SurveyEventName.SENT}', '${SurveyEventName.DISMISSED}')`,
            },
        ],
        after: '-90d',
        orderBy: ['timestamp DESC'],
        limit: 1,
        modifiers: {
            personsOnEventsMode: 'person_id_no_override_properties_on_events',
        },
    }
}

type LastSurveyResponseResult =
    | { status: 'ok'; globals: CyclotronJobInvocationGlobals }
    | { status: 'empty' }
    | { status: 'failed' }

/**
 * Aligns sample globals with the saved notification's first event filter so the test
 * passes the compiled filter bytecode. Without this, a tiny mismatch (e.g. a survey id
 * that drifted from `values.survey.id` due to copying or migration) skips the test.
 */
function alignGlobalsWithNotificationFilter(
    globals: CyclotronJobInvocationGlobals,
    notification: HogFunctionType | null
): CyclotronJobInvocationGlobals {
    const effectiveFilter = notification?.mappings?.[0]?.filters ?? notification?.filters ?? null
    const firstEvent = effectiveFilter?.events?.[0]
    if (!firstEvent) {
        return globals
    }
    const mergedProperties = { ...globals.event.properties }
    for (const prop of firstEvent.properties ?? []) {
        if ('key' in prop && prop.key && 'value' in prop && prop.value !== undefined) {
            mergedProperties[prop.key] = prop.value
        }
    }
    return {
        ...globals,
        event: {
            ...globals.event,
            event: typeof firstEvent.id === 'string' ? firstEvent.id : globals.event.event,
            properties: mergedProperties,
        },
    }
}

async function fetchLastSurveyResponseGlobals(query: EventsQuery | null): Promise<LastSurveyResponseResult> {
    if (!query) {
        return { status: 'empty' }
    }
    try {
        const response = await performQuery(query)
        const row = response?.results?.[0]
        const event = row?.[0] as EventType | undefined
        const person = row?.[1] as PersonType | undefined
        if (!event || !person) {
            return { status: 'empty' }
        }
        return { status: 'ok', globals: convertToHogFunctionInvocationGlobals(event, person) }
    } catch {
        return { status: 'failed' }
    }
}

async function buildSurveyNotificationPayload({
    form,
    survey,
    editingNotification,
    copiedNotification,
}: {
    form: SurveyNotificationForm
    survey: SurveyNotificationContext
    editingNotification: HogFunctionType | null
    copiedNotification: HogFunctionType | null
}): Promise<Partial<HogFunctionType>> {
    const templateId = DESTINATION_OPTIONS.find((option) => option.value === form.destination)?.templateId
    const template = await api.hogFunctions.getTemplate(templateId || 'template-slack')

    if (editingNotification) {
        return updateSurveyNotificationPayload({
            notification: editingNotification,
            template,
            destination: form.destination,
            surveyId: survey.id,
            form,
        })
    }

    if (copiedNotification) {
        return createCopiedSurveyNotificationPayload({
            notification: copiedNotification,
            template,
            destination: form.destination,
            survey,
            form,
        })
    }

    return createSurveyNotificationPayload({
        template,
        destination: form.destination,
        surveyName: survey.name,
        surveyId: survey.id,
        form,
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

function getSentEventPropertiesFromNotification(notification: HogFunctionType): EventPropertyFilter[] {
    const sentEvent = notification.filters?.events?.find((event) => event.id === SurveyEventName.SENT)
    const properties = sentEvent?.properties ?? []
    return properties.filter(
        (property): property is EventPropertyFilter =>
            typeof property === 'object' &&
            property !== null &&
            'type' in property &&
            (property as { type?: unknown }).type === PropertyFilterType.Event
    )
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
    const responseFilters = remapResponses
        ? []
        : parseResponseFiltersFromProperties(getSentEventPropertiesFromNotification(notification), survey.questions)

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
        responseFilters,
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
        filters: getSurveyNotificationFilters(surveyId, buildResponseFilterProperties(form.responseFilters)),
        hog: template.code,
        icon_url: template.icon_url,
        enabled: true,
    }
}

function mergeResponseFiltersIntoExistingFilters(
    existingFilters: HogFunctionType['filters'],
    fallbackFilters: HogFunctionType['filters'],
    responseFilters: SurveyResponseFilter[]
): HogFunctionType['filters'] {
    const base = existingFilters ?? fallbackFilters
    if (!base) {
        return fallbackFilters
    }
    const responseProperties = buildResponseFilterProperties(responseFilters)
    const events = (base.events ?? []).map((event) => {
        if (event.id !== SurveyEventName.SENT) {
            return event
        }
        const preservedProperties = stripResponseFiltersFromProperties(
            (event.properties ?? []).filter(
                (property): property is EventPropertyFilter =>
                    typeof property === 'object' &&
                    property !== null &&
                    'type' in property &&
                    (property as { type?: unknown }).type === PropertyFilterType.Event
            )
        )
        return {
            ...event,
            properties: [...preservedProperties, ...responseProperties],
        }
    })
    return { ...base, events }
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
        filters: mergeResponseFiltersIntoExistingFilters(notification.filters, payload.filters, form.responseFilters),
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
        filters: getSurveyNotificationFilters(survey.id, buildResponseFilterProperties(form.responseFilters)),
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
        values: [
            integrationsLogic,
            ['integrations'],
            surveyLogic({ id: props.surveyId }),
            ['survey', 'surveyLoading', 'surveyNotifications', 'surveyNotificationsLoading'],
        ],
        actions: [
            surveyLogic({ id: props.surveyId }),
            ['loadSurveyNotifications', 'loadSurveyNotificationsSuccess', 'loadSurveySuccess'],
        ],
    })),

    actions({
        openDialog: (payload: OpenSurveyNotificationDialogPayload = {}) => ({
            notification: payload.notification ?? null,
            intent: payload.intent ?? 'add',
        }),
        closeDialog: true,
        setNotificationSubmissionError: (error: string | null) => ({ error }),
        setPendingDeepLink: (target: string | null) => ({ target }),
        consumePendingDeepLink: true,
        clearTestResult: true,
        sendTestNotification: (payload: { source: SurveyNotificationTestSource }) => ({ source: payload.source }),
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
        pendingDeepLink: [
            null as string | null,
            {
                setPendingDeepLink: (_, { target }) => target,
                openDialog: () => null,
            },
        ],
        testResultError: [
            null as string | null,
            {
                sendTestNotification: () => null,
                sendTestNotificationSuccess: () => null,
                sendTestNotificationFailure: (_, { error }) => error || 'Failed to send test notification.',
                openDialog: () => null,
                closeDialog: () => null,
                clearTestResult: () => null,
            },
        ],
    }),

    loaders(({ values }) => ({
        testResult: [
            null as CyclotronJobTestInvocationResult | null,
            {
                clearTestResult: () => null,
                sendTestNotification: async ({ source }) => {
                    const configuration = await buildSurveyNotificationPayload({
                        form: values.notificationForm,
                        survey: values.survey,
                        editingNotification: values.editingNotification,
                        copiedNotification: values.copiedNotification,
                    })

                    let globals: CyclotronJobInvocationGlobals = values.templateGlobals
                    let usingSample = source === 'sample'
                    if (source === 'last_response') {
                        const lookup = await fetchLastSurveyResponseGlobals(values.lastResponseEventQuery)
                        if (lookup.status === 'ok') {
                            globals = lookup.globals
                        } else if (lookup.status === 'failed') {
                            usingSample = true
                            lemonToast.warning(
                                'Could not fetch the last response — sent the test with sample data instead.'
                            )
                        } else {
                            usingSample = true
                            lemonToast.info('No survey responses yet — sent the test with sample data instead.')
                        }
                    }

                    // Align sample globals with the saved filter's expected values so the test
                    // isn't skipped by a $survey_id or completion-flag mismatch. Applies to an
                    // explicit sample-data test and to a last-response test that fell back to it.
                    if (usingSample) {
                        globals = alignGlobalsWithNotificationFilter(globals, values.editingNotification)
                    }

                    const id = values.editingNotification?.id ?? 'new'
                    return await api.hogFunctions.createTestInvocation(id, {
                        configuration: configuration as Record<string, any>,
                        mock_async_functions: false,
                        globals,
                    })
                },
            },
        ],
    })),

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
                const payload = await buildSurveyNotificationPayload({
                    form,
                    survey: values.survey,
                    editingNotification: values.editingNotification,
                    copiedNotification: values.copiedNotification,
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
        lastResponseEventQuery: [
            (s) => [s.survey],
            (survey: SurveyNotificationContext): EventsQuery | null => buildLastSurveyResponseQuery(survey.id),
        ],
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
            actions.clearTestResult()
            actions.setNotificationFormValues(
                notification
                    ? buildSurveyNotificationFormFromNotification(notification, values.survey, intent === 'copy')
                    : buildSurveyNotificationForm(values.survey)
            )
        },
        sendTestNotificationSuccess: ({ testResult }) => {
            if (testResult?.status === 'success') {
                lemonToast.success('Test notification sent.')
            } else if (testResult?.status === 'error') {
                lemonToast.error('Test notification failed — see logs below.')
            }
        },
        sendTestNotificationFailure: ({ error }) => {
            lemonToast.error(error || 'Failed to send test notification.')
        },
        setPendingDeepLink: ({ target }) => {
            if (!target) {
                return
            }
            actions.consumePendingDeepLink()
        },
        loadSurveySuccess: () => {
            if (values.pendingDeepLink) {
                actions.consumePendingDeepLink()
            }
        },
        loadSurveyNotificationsSuccess: () => {
            if (values.pendingDeepLink) {
                actions.consumePendingDeepLink()
            }
        },
        consumePendingDeepLink: () => {
            const target = values.pendingDeepLink
            if (!target || values.isOpen) {
                return
            }
            if (values.surveyLoading || values.survey.id === NEW_SURVEY.id) {
                return
            }
            if (target === 'add') {
                actions.openDialog()
                return
            }
            if (values.surveyNotificationsLoading) {
                return
            }
            const notification = values.surveyNotifications.find((fn) => fn.id === target)
            if (notification) {
                actions.openDialog({ notification, intent: 'edit' })
                return
            }
            // The notification ID didn't resolve (deleted, wrong project, stale link). Clear the
            // pending target so unrelated reloads of surveyNotifications don't keep re-triggering
            // this listener with the same dead ID, and let the user know the link didn't work.
            actions.setPendingDeepLink(null)
            lemonToast.error("We couldn't find that notification — it may have been removed.")
        },
        closeDialog: () => {
            actions.resetNotificationForm()
            actions.clearTestResult()
            // If a deep link arrived while another dialog was already open it stayed pending —
            // try to consume it now that we're no longer blocked by `isOpen`.
            if (values.pendingDeepLink) {
                actions.consumePendingDeepLink()
            }
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

    urlToAction(({ actions, props }) => ({
        [urls.survey(props.surveyId)]: (_, searchParams) => {
            const target = searchParams.notification
            if (typeof target === 'string' && target.length > 0) {
                actions.setPendingDeepLink(target)
            }
        },
    })),

    actionToUrl(() => ({
        setPendingDeepLink: () => {
            if (!('notification' in router.values.searchParams)) {
                return
            }
            const { notification: _consumed, ...rest } = router.values.searchParams
            return [router.values.location.pathname, rest, router.values.hashParams, { replace: true }]
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
