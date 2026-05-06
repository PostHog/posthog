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
    RESPONDENT_DETAILS_LINE,
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

function SectionEyebrow({ children }: { children: string }): JSX.Element {
    return <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted">{children}</div>
}

type MessageFormattingActionProps = {
    questions: SurveyQuestionForNotification[]
    onReset: () => void
    onInsertSurveyName: () => void
    onInsertRespondentDetails: () => void
    onInsertQuestion: (question: SurveyQuestionForNotification, index: number) => void
}

function MessageFormattingActions({
    questions,
    onReset,
    onInsertSurveyName,
    onInsertRespondentDetails,
    onInsertQuestion,
}: MessageFormattingActionProps): JSX.Element {
    const applicableQuestions = questions.filter((question) => question.id && question.type !== SurveyQuestionType.Link)

    return (
        <div className="space-y-3">
            <div className="border-t border-border" />
            <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
                <div className="text-xs font-medium text-default">Quick inserts</div>
                <div className="text-xs text-muted">Keep the default compact, then add context only where needed.</div>
            </div>
            <div className="flex flex-wrap gap-1.5">
                <LemonButton size="xsmall" type="secondary" onClick={onReset}>
                    Use suggested format
                </LemonButton>
                <LemonButton size="xsmall" type="tertiary" onClick={onInsertSurveyName}>
                    Insert survey name
                </LemonButton>
                <LemonButton size="xsmall" type="tertiary" onClick={onInsertRespondentDetails}>
                    Insert respondent details
                </LemonButton>
                {applicableQuestions.map((question, index) => (
                    <LemonButton
                        key={question.id}
                        size="xsmall"
                        type="tertiary"
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
        onInsertRespondentDetails: () =>
            setNotificationFormValue(field, appendTemplateLine(value, RESPONDENT_DETAILS_LINE)),
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
            description="Send survey updates to Slack, Discord, Microsoft Teams, or a webhook."
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
            <div className="flex flex-col gap-3">
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
                    <div className="flex flex-col gap-3">
                        <div className="space-y-2">
                            <Field name="destination" label="Destination">
                                {({ value, onChange }) => (
                                    <LemonSelect
                                        value={value}
                                        onChange={onChange}
                                        options={DESTINATION_OPTIONS.map((option) => ({
                                            value: option.value,
                                            label: option.label,
                                            icon: (
                                                <img src={option.iconUrl} alt="" className="h-5 w-5 object-contain" />
                                            ),
                                        }))}
                                        fullWidth
                                    />
                                )}
                            </Field>
                            <div className="text-xs text-muted">
                                {destinationDeliveryDescription(notificationForm.destination)}
                            </div>
                            <div className="text-xs text-muted">
                                Notifications send when a survey is completed or dismissed after at least one response.
                                If someone closes it without answering or leaves it open forever, nothing is sent.
                            </div>
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
                                <Field name="slackMessage">
                                    {({ value, onChange }) => (
                                        <div className="space-y-3">
                                            <div className="border-t border-border" />
                                            <div className="space-y-1">
                                                <div className="text-sm font-medium text-default">
                                                    Slack message template
                                                </div>
                                                <div className="text-xs text-muted">
                                                    Built for scanning fast in busy channels, with optional details
                                                    below.
                                                </div>
                                            </div>
                                            <TemplateEditor
                                                value={value}
                                                onChange={onChange}
                                                globals={templateGlobals}
                                            />
                                            {messageFormattingActions ? (
                                                <MessageFormattingActions {...messageFormattingActions} />
                                            ) : null}
                                            <div className="space-y-3">
                                                <div className="border-t border-border" />
                                                <Field name="includeSlackButtons">
                                                    {({ value: switchValue, onChange: switchOnChange }) => (
                                                        <LemonSwitch
                                                            checked={switchValue}
                                                            onChange={switchOnChange}
                                                            label="Include buttons to view the survey and person"
                                                        />
                                                    )}
                                                </Field>
                                            </div>
                                        </div>
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
                                <Field name="discordMessage">
                                    {({ value, onChange }) => (
                                        <div className="space-y-3">
                                            <div className="border-t border-border" />
                                            <div className="space-y-1">
                                                <div className="text-sm font-medium text-default">
                                                    Discord message template
                                                </div>
                                                <div className="text-xs text-muted">
                                                    Keep it compact by default, then use quick inserts when you need
                                                    more context.
                                                </div>
                                            </div>
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
                                <Field name="teamsMessage">
                                    {({ value, onChange }) => (
                                        <div className="space-y-3">
                                            <div className="border-t border-border" />
                                            <div className="space-y-1">
                                                <div className="text-sm font-medium text-default">
                                                    Microsoft Teams message template
                                                </div>
                                                <div className="text-xs text-muted">
                                                    Default to a high-signal summary and add metadata only if the team
                                                    needs it.
                                                </div>
                                            </div>
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
                                <div className="space-y-3">
                                    <div className="border-t border-border" />
                                    <div className="space-y-1">
                                        <div className="text-sm font-medium text-default">Webhook request body</div>
                                        <div className="text-xs text-muted">
                                            Survey webhooks send the trigger status, survey metadata, person context,
                                            and one answer field per question.
                                        </div>
                                    </div>
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
                                        <div className="flex-1 text-xs text-muted">
                                            Tailor the JSON before saving it if your endpoint expects a specific shape.
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
                                </div>
                            </>
                        ) : null}

                        <div className="space-y-3">
                            <div className="border-t border-border" />
                            <SectionEyebrow>Reference</SectionEyebrow>
                            <div className="space-y-1">
                                <div className="text-sm font-medium">Available survey placeholders</div>
                                <div className="text-xs text-muted">
                                    Need deeper customization later? After you create a notification, open it from the
                                    survey notifications list to use the full Hog function editor.
                                </div>
                            </div>
                            <SurveyResponseKeysReference questions={survey.questions} />
                        </div>
                    </div>
                </Form>
            </div>
        </LemonModal>
    )
}
