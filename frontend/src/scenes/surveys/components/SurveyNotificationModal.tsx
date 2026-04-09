import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { DESTINATION_OPTIONS, DestinationKey } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import {
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
    HOG_FUNCTION_SUB_TEMPLATES,
} from 'scenes/hog-functions/sub-templates/sub-templates'
import { SurveyResponseKeysReference } from 'scenes/surveys/components/SurveyResponseKeysReference'
import { NEW_SURVEY } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyNotificationFilters, getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

import { HogFunctionTemplateType, HogFunctionType, SurveyQuestionType } from '~/types'

const WEBHOOK_METHOD_OPTIONS = [
    { value: 'POST', label: 'POST' },
    { value: 'PUT', label: 'PUT' },
    { value: 'PATCH', label: 'PATCH' },
    { value: 'GET', label: 'GET' },
    { value: 'DELETE', label: 'DELETE' },
]

type SurveyQuestionForNotification = {
    id?: string
    question: string | null | undefined
    type: SurveyQuestionType
}

const MAX_EXAMPLE_QUESTIONS = 3
const SURVEY_NAME_TOKEN = "{event.properties['$survey_name']}"
const SURVEY_ID_TOKEN = "{event.properties['$survey_id']}"
const RESPONDENT_NAME_TOKEN = '{person.name}'
const RESPONDENT_EMAIL_TOKEN = '{person.properties.email}'

function getResponseToken(questionId: string): string {
    return `{event.properties['${getSurveyIdBasedResponseKey(questionId)}']}`
}

function getQuestionLabel(question: SurveyQuestionForNotification, index: number): string {
    return question.question?.trim() || `Question ${index + 1}`
}

function getQuestionLine(question: SurveyQuestionForNotification, index: number): string {
    return `- ${getQuestionLabel(question, index)}: ${getResponseToken(question.id!)}`
}

function getDefaultSurveyMessage(questions: SurveyQuestionForNotification[] = []): string {
    const exampleQuestions = questions
        .filter((question) => question.id && question.type !== SurveyQuestionType.Link)
        .slice(0, MAX_EXAMPLE_QUESTIONS)

    return [
        '*New survey response*',
        `Survey: *${SURVEY_NAME_TOKEN}*`,
        `Respondent: ${RESPONDENT_NAME_TOKEN}`,
        `Email: ${RESPONDENT_EMAIL_TOKEN}`,
        ...(exampleQuestions.length > 0
            ? ['', '*Responses*', ...exampleQuestions.map((question, index) => getQuestionLine(question, index))]
            : []),
    ].join('\n')
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

function appendQuestionToken(value: string, question: SurveyQuestionForNotification, index: number): string {
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

function appendTemplateLine(value: string, line: string): string {
    const trimmedValue = value.trim()

    if (trimmedValue.includes(line)) {
        return trimmedValue
    }

    return trimmedValue ? `${trimmedValue}\n${line}` : line
}

function notificationNameFor(destination: DestinationKey, surveyName?: string | null): string {
    const destinationLabel = DESTINATION_OPTIONS.find((option) => option.value === destination)?.label || 'Notification'
    const baseName = surveyName?.trim() || 'Survey'
    return `${baseName} → ${destinationLabel}`
}

function destinationDeliveryDescription(destination: DestinationKey): string {
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

function TemplateEditor({
    value,
    onChange,
    globals,
    minHeight = '7rem',
}: {
    value: string
    onChange: (value: string) => void
    globals: Record<string, any>
    minHeight?: string
}): JSX.Element {
    return (
        <CodeEditorResizeable
            embedded
            language="hogTemplate"
            value={value}
            onChange={(nextValue) => onChange(nextValue ?? '')}
            globals={globals}
            minHeight={minHeight}
            maxHeight="14rem"
            allowManualResize={false}
            options={{
                wordWrap: 'on',
                minimap: { enabled: false },
                lineNumbers: 'off',
                scrollBeyondLastLine: false,
                fixedOverflowWidgets: true,
                suggest: {
                    showInlineDetails: true,
                },
                quickSuggestionsDelay: 200,
            }}
        />
    )
}

function MessageFormattingActions({
    questions,
    onReset,
    onInsertSurveyName,
    onInsertRespondent,
    onInsertEmail,
    onInsertQuestion,
}: {
    questions: SurveyQuestionForNotification[]
    onReset: () => void
    onInsertSurveyName: () => void
    onInsertRespondent: () => void
    onInsertEmail: () => void
    onInsertQuestion: (question: SurveyQuestionForNotification, index: number) => void
}): JSX.Element {
    const applicableQuestions = questions.filter((question) => question.id && question.type !== SurveyQuestionType.Link)

    return (
        <div className="rounded border border-dashed bg-surface-primary p-2">
            <div className="mb-2 text-xs text-muted">
                Start with a readable template, then add survey answers or metadata as needed.
            </div>
            <div className="flex flex-wrap gap-1.5">
                <LemonButton size="xsmall" type="secondary" onClick={onReset}>
                    Use suggested format
                </LemonButton>
                <LemonButton size="xsmall" type="secondary" onClick={onInsertSurveyName}>
                    Insert survey name
                </LemonButton>
                <LemonButton size="xsmall" type="secondary" onClick={onInsertRespondent}>
                    Insert respondent
                </LemonButton>
                <LemonButton size="xsmall" type="secondary" onClick={onInsertEmail}>
                    Insert email
                </LemonButton>
                {applicableQuestions.map((question, index) => (
                    <LemonButton
                        key={question.id}
                        size="xsmall"
                        type="secondary"
                        onClick={() => onInsertQuestion(question, index)}
                    >
                        Insert: {getQuestionLabel(question, index)}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}

function createSurveyNotificationPayload({
    template,
    destination,
    surveyName,
    surveyId,
    slackIntegrationId,
    slackChannel,
    slackMessage,
    includeSlackButtons,
    discordWebhookUrl,
    discordMessage,
    teamsWebhookUrl,
    teamsMessage,
    webhookUrl,
    webhookMethod,
    webhookBody,
}: {
    template: HogFunctionTemplateType
    destination: DestinationKey
    surveyName?: string | null
    surveyId: string
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
}): Partial<HogFunctionType> {
    const destinationOption = DESTINATION_OPTIONS.find((option) => option.value === destination)
    if (!destinationOption) {
        throw new Error('Unsupported destination')
    }

    const subTemplate = HOG_FUNCTION_SUB_TEMPLATES['survey-response'].find(
        (template) => template.template_id === destinationOption.templateId
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
            if (!slackIntegrationId || !slackChannel) {
                throw new Error('Select a Slack workspace and channel.')
            }
            inputs.slack_workspace = { value: slackIntegrationId }
            inputs.channel = { value: slackChannel.split('|')[0] }
            inputs.text = { value: slackMessage.trim() }
            inputs.blocks = { value: buildSlackBlocks(slackMessage.trim(), includeSlackButtons) }
            break
        case 'discord':
            inputs.webhookUrl = { value: discordWebhookUrl.trim() }
            inputs.content = { value: discordMessage.trim() }
            break
        case 'microsoft-teams':
            inputs.webhookUrl = { value: teamsWebhookUrl.trim() }
            inputs.text = { value: teamsMessage.trim() }
            break
        case 'webhook':
            inputs.url = { value: webhookUrl.trim() }
            inputs.method = { value: webhookMethod }
            inputs.body = { value: JSON.parse(webhookBody) }
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

export function SurveyNotificationModal({ surveyId }: { surveyId: string }): JSX.Element {
    const logic = surveyLogic({ id: surveyId })
    const { survey, surveyNotificationModalOpen } = useValues(logic)
    const { closeSurveyNotificationModal, loadSurveyNotifications } = useActions(logic)
    const { integrations } = useValues(integrationsLogic)

    const [destination, setDestination] = useState<DestinationKey>('slack')
    const [slackIntegrationId, setSlackIntegrationId] = useState<number | null>(null)
    const [slackChannel, setSlackChannel] = useState<string | null>(null)
    const [slackMessage, setSlackMessage] = useState(() => getDefaultSurveyMessage(survey.questions))
    const [includeSlackButtons, setIncludeSlackButtons] = useState(true)
    const [discordWebhookUrl, setDiscordWebhookUrl] = useState('')
    const [discordMessage, setDiscordMessage] = useState(() => getDefaultSurveyMessage(survey.questions))
    const [teamsWebhookUrl, setTeamsWebhookUrl] = useState('')
    const [teamsMessage, setTeamsMessage] = useState(() => getDefaultSurveyMessage(survey.questions))
    const [webhookUrl, setWebhookUrl] = useState('')
    const [webhookMethod, setWebhookMethod] = useState('POST')
    const [webhookBody, setWebhookBody] = useState('')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const selectedSlackIntegration = integrations?.find((integration) => integration.id === slackIntegrationId) ?? null
    const hasSlackIntegration = integrations?.some((integration) => integration.kind === 'slack') ?? false

    const defaultWebhookBody = useMemo(
        () => JSON.stringify(buildWebhookBodyTemplate(survey.questions), null, 2),
        [survey.questions]
    )
    const templateGlobals = useMemo(() => {
        const responseProperties = Object.fromEntries(
            survey.questions
                .filter((question) => question.id && question.type !== SurveyQuestionType.Link)
                .map((question, index) => [
                    getSurveyIdBasedResponseKey(question.id!),
                    question.question || `Example answer ${index + 1}`,
                ])
        )

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
                timestamp: '2026-04-09T12:00:00Z',
                properties: {
                    $survey_id: survey.id === NEW_SURVEY.id ? 'survey-id' : survey.id,
                    $survey_name: survey.name || 'Survey',
                    $survey_completed: true,
                    ...responseProperties,
                },
                url: 'https://app.posthog.com/project/1/events/example/2026-04-09T12%3A00%3A00Z',
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
    }, [survey.id, survey.name, survey.questions])

    useEffect(() => {
        if (!surveyNotificationModalOpen) {
            return
        }

        setDestination('slack')
        setSlackIntegrationId(null)
        setSlackChannel(null)
        setSlackMessage(getDefaultSurveyMessage(survey.questions))
        setIncludeSlackButtons(true)
        setDiscordWebhookUrl('')
        setDiscordMessage(getDefaultSurveyMessage(survey.questions))
        setTeamsWebhookUrl('')
        setTeamsMessage(getDefaultSurveyMessage(survey.questions))
        setWebhookUrl('')
        setWebhookMethod('POST')
        setWebhookBody(defaultWebhookBody)
        setIsSubmitting(false)
        setError(null)
    }, [defaultWebhookBody, survey.questions, surveyNotificationModalOpen])

    const submitDisabledReason = useMemo(() => {
        if (survey.id === NEW_SURVEY.id) {
            return 'Save the survey before creating notifications.'
        }
        if (isSubmitting) {
            return 'Creating notification...'
        }

        switch (destination) {
            case 'slack':
                if (!hasSlackIntegration) {
                    return 'Configure Slack for this project first.'
                }
                if (!slackIntegrationId) {
                    return 'Select a Slack workspace.'
                }
                if (!slackChannel) {
                    return 'Select a Slack channel.'
                }
                if (!slackMessage.trim()) {
                    return 'Enter the Slack message.'
                }
                return undefined
            case 'discord':
                if (!discordMessage.trim()) {
                    return 'Enter the Discord message.'
                }
                if (!isValidHttpUrl(discordWebhookUrl.trim())) {
                    return 'Enter a valid Discord webhook URL.'
                }
                return undefined
            case 'microsoft-teams':
                if (!teamsMessage.trim()) {
                    return 'Enter the Microsoft Teams message.'
                }
                if (!isValidHttpUrl(teamsWebhookUrl.trim())) {
                    return 'Enter a valid Microsoft Teams webhook URL.'
                }
                return undefined
            case 'webhook':
                if (!isValidHttpUrl(webhookUrl.trim())) {
                    return 'Enter a valid webhook URL.'
                }
                try {
                    JSON.parse(webhookBody)
                } catch {
                    return 'Enter valid JSON for the webhook body.'
                }
                return undefined
        }
    }, [
        destination,
        discordMessage,
        discordWebhookUrl,
        hasSlackIntegration,
        isSubmitting,
        slackChannel,
        slackIntegrationId,
        slackMessage,
        survey.id,
        teamsMessage,
        teamsWebhookUrl,
        webhookBody,
        webhookUrl,
    ])

    const onSubmit = async (): Promise<void> => {
        if (submitDisabledReason) {
            return
        }

        setError(null)
        setIsSubmitting(true)

        try {
            const templateId = DESTINATION_OPTIONS.find((option) => option.value === destination)?.templateId
            const template = await api.hogFunctions.getTemplate(templateId || 'template-slack')

            const payload = createSurveyNotificationPayload({
                template,
                destination,
                surveyName: survey.name,
                surveyId: survey.id,
                slackIntegrationId,
                slackChannel,
                slackMessage,
                includeSlackButtons,
                discordWebhookUrl,
                discordMessage,
                teamsWebhookUrl,
                teamsMessage,
                webhookUrl,
                webhookMethod,
                webhookBody,
            })

            const response = await api.hogFunctions.create(payload)

            await loadSurveyNotifications()
            closeSurveyNotificationModal()
            lemonToast.success(`Notification "${response.name}" created`)
        } catch (e) {
            const message = e instanceof Error ? e.message : 'Failed to create notification. Please try again.'
            setError(message)
        } finally {
            setIsSubmitting(false)
        }
    }

    return (
        <LemonModal
            isOpen={surveyNotificationModalOpen}
            onClose={closeSurveyNotificationModal}
            title="Add survey notification"
            description="Send survey responses to Slack, Discord, Microsoft Teams, or a webhook without leaving this page."
            width={720}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSurveyNotificationModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => void onSubmit()}
                        loading={isSubmitting}
                        disabledReason={submitDisabledReason}
                    >
                        Add notification
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {error ? <div className="text-sm text-danger">{error}</div> : null}

                <div className="flex flex-col gap-2">
                    <label className="text-sm font-medium">Destination</label>
                    <LemonSelect
                        value={destination}
                        onChange={(value) => setDestination(value)}
                        options={DESTINATION_OPTIONS.map((option) => ({
                            value: option.value,
                            label: option.label,
                            icon: <img src={option.iconUrl} alt="" className="h-5 w-5 object-contain" />,
                        }))}
                        fullWidth
                    />
                    <div className="text-xs text-muted">{destinationDeliveryDescription(destination)}</div>
                    <div className="text-xs text-muted">
                        Tailored to surveys: notifications fire only for completed submissions by default.
                    </div>
                </div>

                {destination === 'slack' ? (
                    <>
                        {!hasSlackIntegration ? (
                            <SlackNotConfiguredBanner />
                        ) : (
                            <>
                                <div className="flex flex-col gap-2">
                                    <label className="text-sm font-medium">Slack workspace</label>
                                    <IntegrationChoice
                                        integration="slack"
                                        value={slackIntegrationId ?? undefined}
                                        onChange={(value) => {
                                            setSlackIntegrationId(value ?? null)
                                            setSlackChannel(null)
                                        }}
                                    />
                                </div>
                                {selectedSlackIntegration ? (
                                    <div className="flex flex-col gap-2">
                                        <label className="text-sm font-medium">Channel</label>
                                        <SlackChannelPicker
                                            value={slackChannel ?? undefined}
                                            onChange={(value) => setSlackChannel(value ?? null)}
                                            integration={selectedSlackIntegration}
                                        />
                                    </div>
                                ) : null}
                            </>
                        )}
                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-medium">Message</label>
                            <TemplateEditor value={slackMessage} onChange={setSlackMessage} globals={templateGlobals} />
                            <MessageFormattingActions
                                questions={survey.questions}
                                onReset={() => setSlackMessage(getDefaultSurveyMessage(survey.questions))}
                                onInsertSurveyName={() =>
                                    setSlackMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Survey: *${SURVEY_NAME_TOKEN}*`)
                                    )
                                }
                                onInsertRespondent={() =>
                                    setSlackMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Respondent: ${RESPONDENT_NAME_TOKEN}`)
                                    )
                                }
                                onInsertEmail={() =>
                                    setSlackMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Email: ${RESPONDENT_EMAIL_TOKEN}`)
                                    )
                                }
                                onInsertQuestion={(question, index) =>
                                    setSlackMessage((currentValue) =>
                                        appendQuestionToken(currentValue, question, index)
                                    )
                                }
                            />
                        </div>
                        <LemonSwitch
                            checked={includeSlackButtons}
                            onChange={setIncludeSlackButtons}
                            label="Include buttons to view the survey and person"
                            bordered
                        />
                    </>
                ) : null}

                {destination === 'discord' ? (
                    <>
                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-medium">Discord webhook URL</label>
                            <LemonInput
                                value={discordWebhookUrl}
                                onChange={setDiscordWebhookUrl}
                                placeholder="https://discord.com/api/webhooks/..."
                                fullWidth
                            />
                        </div>
                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-medium">Message</label>
                            <TemplateEditor
                                value={discordMessage}
                                onChange={setDiscordMessage}
                                globals={templateGlobals}
                            />
                            <MessageFormattingActions
                                questions={survey.questions}
                                onReset={() => setDiscordMessage(getDefaultSurveyMessage(survey.questions))}
                                onInsertSurveyName={() =>
                                    setDiscordMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Survey: *${SURVEY_NAME_TOKEN}*`)
                                    )
                                }
                                onInsertRespondent={() =>
                                    setDiscordMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Respondent: ${RESPONDENT_NAME_TOKEN}`)
                                    )
                                }
                                onInsertEmail={() =>
                                    setDiscordMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Email: ${RESPONDENT_EMAIL_TOKEN}`)
                                    )
                                }
                                onInsertQuestion={(question, index) =>
                                    setDiscordMessage((currentValue) =>
                                        appendQuestionToken(currentValue, question, index)
                                    )
                                }
                            />
                        </div>
                    </>
                ) : null}

                {destination === 'microsoft-teams' ? (
                    <>
                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-medium">Microsoft Teams webhook URL</label>
                            <LemonInput
                                value={teamsWebhookUrl}
                                onChange={setTeamsWebhookUrl}
                                placeholder="https://..."
                                fullWidth
                            />
                        </div>
                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-medium">Message</label>
                            <TemplateEditor value={teamsMessage} onChange={setTeamsMessage} globals={templateGlobals} />
                            <MessageFormattingActions
                                questions={survey.questions}
                                onReset={() => setTeamsMessage(getDefaultSurveyMessage(survey.questions))}
                                onInsertSurveyName={() =>
                                    setTeamsMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Survey: *${SURVEY_NAME_TOKEN}*`)
                                    )
                                }
                                onInsertRespondent={() =>
                                    setTeamsMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Respondent: ${RESPONDENT_NAME_TOKEN}`)
                                    )
                                }
                                onInsertEmail={() =>
                                    setTeamsMessage((currentValue) =>
                                        appendTemplateLine(currentValue, `Email: ${RESPONDENT_EMAIL_TOKEN}`)
                                    )
                                }
                                onInsertQuestion={(question, index) =>
                                    setTeamsMessage((currentValue) =>
                                        appendQuestionToken(currentValue, question, index)
                                    )
                                }
                            />
                        </div>
                    </>
                ) : null}

                {destination === 'webhook' ? (
                    <>
                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-medium">Webhook URL</label>
                            <LemonInput
                                value={webhookUrl}
                                onChange={setWebhookUrl}
                                placeholder="https://..."
                                fullWidth
                            />
                        </div>
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-4">
                            <div className="flex min-w-48 flex-col gap-2">
                                <label className="text-sm font-medium">HTTP method</label>
                                <LemonSelect
                                    value={webhookMethod}
                                    onChange={setWebhookMethod}
                                    options={WEBHOOK_METHOD_OPTIONS}
                                    fullWidth
                                />
                            </div>
                            <div className="flex-1 rounded border border-dashed bg-surface-primary p-3 text-xs text-muted">
                                Survey webhooks send the survey metadata, person context, and one answer field per
                                question. You can tailor the payload before saving it.
                            </div>
                        </div>
                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-medium">JSON body</label>
                            <CodeEditorResizeable
                                embedded
                                language="json"
                                value={webhookBody}
                                onChange={(nextValue) => setWebhookBody(nextValue ?? '')}
                                minHeight="14rem"
                                maxHeight="20rem"
                                allowManualResize={false}
                                options={{
                                    minimap: { enabled: false },
                                    scrollBeyondLastLine: false,
                                    fixedOverflowWidgets: true,
                                }}
                            />
                        </div>
                    </>
                ) : null}

                <div className="rounded border bg-fill-secondary p-3">
                    <div className="mb-2 text-sm font-medium">Available survey placeholders</div>
                    <div className="mb-3 text-xs text-muted">
                        Need deeper customization later? After you create a notification, open it from the survey
                        notifications list to use the full Hog function editor.
                    </div>
                    <SurveyResponseKeysReference questions={survey.questions} />
                </div>
            </div>
        </LemonModal>
    )
}
