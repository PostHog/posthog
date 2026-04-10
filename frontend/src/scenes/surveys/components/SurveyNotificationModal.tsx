import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { DESTINATION_OPTIONS } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import { SurveyResponseKeysReference } from 'scenes/surveys/components/SurveyResponseKeysReference'
import {
    RESPONDENT_EMAIL_TOKEN,
    RESPONDENT_NAME_TOKEN,
    SURVEY_NAME_TOKEN,
    SurveyNotificationForm,
    SurveyQuestionForNotification,
    WEBHOOK_METHOD_OPTIONS,
    appendQuestionToken,
    appendTemplateLine,
    destinationDeliveryDescription,
    getDefaultSurveyMessage,
    getMessageFieldForDestination,
    getQuestionLabel,
    surveyNotificationModalLogic,
} from 'scenes/surveys/surveyNotificationModalLogic'

import { SurveyQuestionType } from '~/types'

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

type MessageFormattingActionProps = {
    questions: SurveyQuestionForNotification[]
    onReset: () => void
    onInsertSurveyName: () => void
    onInsertRespondent: () => void
    onInsertEmail: () => void
    onInsertQuestion: (question: SurveyQuestionForNotification, index: number) => void
}

function MessageFormattingActions({
    questions,
    onReset,
    onInsertSurveyName,
    onInsertRespondent,
    onInsertEmail,
    onInsertQuestion,
}: MessageFormattingActionProps): JSX.Element {
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

function getMessageFormattingActions({
    field,
    value,
    questions,
    setNotificationFormValue,
}: {
    field: 'slackMessage' | 'discordMessage' | 'teamsMessage'
    value: string
    questions: SurveyQuestionForNotification[]
    setNotificationFormValue: <K extends keyof SurveyNotificationForm>(key: K, value: SurveyNotificationForm[K]) => void
}): MessageFormattingActionProps {
    return {
        questions,
        onReset: () => setNotificationFormValue(field, getDefaultSurveyMessage(questions)),
        onInsertSurveyName: () =>
            setNotificationFormValue(field, appendTemplateLine(value, `Survey: *${SURVEY_NAME_TOKEN}*`)),
        onInsertRespondent: () =>
            setNotificationFormValue(field, appendTemplateLine(value, `Respondent: ${RESPONDENT_NAME_TOKEN}`)),
        onInsertEmail: () =>
            setNotificationFormValue(field, appendTemplateLine(value, `Email: ${RESPONDENT_EMAIL_TOKEN}`)),
        onInsertQuestion: (question, index) =>
            setNotificationFormValue(field, appendQuestionToken(value, question, index)),
    }
}

export function SurveyNotificationModal({ surveyId }: { surveyId: string }): JSX.Element {
    const logicProps = { surveyId }
    const logic = surveyNotificationModalLogic(logicProps)
    const {
        isOpen,
        survey,
        notificationForm,
        isNotificationFormSubmitting,
        selectedSlackIntegration,
        hasSlackIntegration,
        templateGlobals,
        submitDisabledReason,
        notificationSubmissionError,
    } = useValues(logic)
    const { closeDialog, setNotificationFormValue } = useActions(logic)

    const messageField = getMessageFieldForDestination(notificationForm.destination)
    const messageFormattingActions =
        messageField !== null
            ? getMessageFormattingActions({
                  field: messageField,
                  value: notificationForm[messageField],
                  questions: survey.questions,
                  setNotificationFormValue,
              })
            : null

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeDialog}
            title="Add survey notification"
            description="Send survey responses to Slack, Discord, Microsoft Teams, or a webhook without leaving this page."
            width={720}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeDialog}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form="survey-notification-form"
                        htmlType="submit"
                        loading={isNotificationFormSubmitting}
                        disabledReason={submitDisabledReason}
                    >
                        Add notification
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {notificationSubmissionError ? (
                    <div className="text-sm text-danger">{notificationSubmissionError}</div>
                ) : null}

                <Form
                    logic={surveyNotificationModalLogic}
                    props={logicProps}
                    formKey="notificationForm"
                    id="survey-notification-form"
                    enableFormOnSubmit
                >
                    <div className="flex flex-col gap-4">
                        <Field name="destination" label="Destination">
                            {({ value, onChange }) => (
                                <LemonSelect
                                    value={value}
                                    onChange={onChange}
                                    options={DESTINATION_OPTIONS.map((option) => ({
                                        value: option.value,
                                        label: option.label,
                                        icon: <img src={option.iconUrl} alt="" className="h-5 w-5 object-contain" />,
                                    }))}
                                    fullWidth
                                />
                            )}
                        </Field>

                        <div className="text-xs text-muted">
                            {destinationDeliveryDescription(notificationForm.destination)}
                        </div>
                        <div className="text-xs text-muted">
                            Tailored to surveys: notifications fire only for completed submissions by default.
                        </div>

                        {notificationForm.destination === 'slack' ? (
                            <>
                                {!hasSlackIntegration ? (
                                    <SlackNotConfiguredBanner />
                                ) : (
                                    <>
                                        <Field name="slackIntegrationId" label="Slack workspace">
                                            {({ value, onChange }) => (
                                                <IntegrationChoice
                                                    integration="slack"
                                                    value={value ?? undefined}
                                                    onChange={(nextValue) => {
                                                        onChange(nextValue ?? null)
                                                        setNotificationFormValue('slackChannel', null)
                                                    }}
                                                />
                                            )}
                                        </Field>
                                        {selectedSlackIntegration ? (
                                            <Field name="slackChannel" label="Channel">
                                                {({ value, onChange }) => (
                                                    <SlackChannelPicker
                                                        value={value ?? undefined}
                                                        onChange={(nextValue) => onChange(nextValue ?? null)}
                                                        integration={selectedSlackIntegration}
                                                    />
                                                )}
                                            </Field>
                                        ) : null}
                                    </>
                                )}
                                <Field name="slackMessage" label="Message">
                                    {({ value, onChange }) => (
                                        <div className="flex flex-col gap-2">
                                            <TemplateEditor
                                                value={value}
                                                onChange={onChange}
                                                globals={templateGlobals}
                                            />
                                            {messageFormattingActions ? (
                                                <MessageFormattingActions {...messageFormattingActions} />
                                            ) : null}
                                        </div>
                                    )}
                                </Field>
                                <Field name="includeSlackButtons">
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            checked={value}
                                            onChange={onChange}
                                            label="Include buttons to view the survey and person"
                                            bordered
                                        />
                                    )}
                                </Field>
                            </>
                        ) : null}

                        {notificationForm.destination === 'discord' ? (
                            <>
                                <Field name="discordWebhookUrl" label="Discord webhook URL">
                                    {({ value, onChange }) => (
                                        <LemonInput
                                            value={value}
                                            onChange={onChange}
                                            placeholder="https://discord.com/api/webhooks/..."
                                            fullWidth
                                        />
                                    )}
                                </Field>
                                <Field name="discordMessage" label="Message">
                                    {({ value, onChange }) => (
                                        <div className="flex flex-col gap-2">
                                            <TemplateEditor
                                                value={value}
                                                onChange={onChange}
                                                globals={templateGlobals}
                                            />
                                            {messageFormattingActions ? (
                                                <MessageFormattingActions {...messageFormattingActions} />
                                            ) : null}
                                        </div>
                                    )}
                                </Field>
                            </>
                        ) : null}

                        {notificationForm.destination === 'microsoft-teams' ? (
                            <>
                                <Field name="teamsWebhookUrl" label="Microsoft Teams webhook URL">
                                    {({ value, onChange }) => (
                                        <LemonInput
                                            value={value}
                                            onChange={onChange}
                                            placeholder="https://..."
                                            fullWidth
                                        />
                                    )}
                                </Field>
                                <Field name="teamsMessage" label="Message">
                                    {({ value, onChange }) => (
                                        <div className="flex flex-col gap-2">
                                            <TemplateEditor
                                                value={value}
                                                onChange={onChange}
                                                globals={templateGlobals}
                                            />
                                            {messageFormattingActions ? (
                                                <MessageFormattingActions {...messageFormattingActions} />
                                            ) : null}
                                        </div>
                                    )}
                                </Field>
                            </>
                        ) : null}

                        {notificationForm.destination === 'webhook' ? (
                            <>
                                <Field name="webhookUrl" label="Webhook URL">
                                    {({ value, onChange }) => (
                                        <LemonInput
                                            value={value}
                                            onChange={onChange}
                                            placeholder="https://..."
                                            fullWidth
                                        />
                                    )}
                                </Field>
                                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-4">
                                    <div className="flex min-w-48 flex-col gap-2">
                                        <Field name="webhookMethod" label="HTTP method">
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    value={value}
                                                    onChange={onChange}
                                                    options={WEBHOOK_METHOD_OPTIONS}
                                                    fullWidth
                                                />
                                            )}
                                        </Field>
                                    </div>
                                    <div className="flex-1 rounded border border-dashed bg-surface-primary p-3 text-xs text-muted">
                                        Survey webhooks send the survey metadata, person context, and one answer field
                                        per question. You can tailor the payload before saving it.
                                    </div>
                                </div>
                                <Field name="webhookBody" label="JSON body">
                                    {({ value, onChange }) => (
                                        <CodeEditorResizeable
                                            embedded
                                            language="json"
                                            value={value}
                                            onChange={(nextValue) => onChange(nextValue ?? '')}
                                            minHeight="14rem"
                                            maxHeight="20rem"
                                            allowManualResize={false}
                                            options={{
                                                minimap: { enabled: false },
                                                scrollBeyondLastLine: false,
                                                fixedOverflowWidgets: true,
                                            }}
                                        />
                                    )}
                                </Field>
                            </>
                        ) : null}

                        <div className="rounded border bg-fill-secondary p-3">
                            <div className="mb-2 text-sm font-medium">Available survey placeholders</div>
                            <div className="mb-3 text-xs text-muted">
                                Need deeper customization later? After you create a notification, open it from the
                                survey notifications list to use the full Hog function editor.
                            </div>
                            <SurveyResponseKeysReference questions={survey.questions} />
                        </div>
                    </div>
                </Form>
            </div>
        </LemonModal>
    )
}
