import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconChevronLeft } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { UsageLimitPaywall } from 'lib/components/PayGateMini/UsageLimitPaywall'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { DashboardType, InsightShortId } from '~/types'

import { InsightSelector } from '../InsightSelector'
import { subscriptionLogic } from '../subscriptionLogic'

const AI_PROMPT_CHAR_LIMIT = 4000

// Shown wherever AI subscriptions are gated off (org hasn't approved AI data
// processing). Mirrors the backend gate in `_ai_create_gate_reason`, which 403s
// the create regardless — so the form must block before submit, not after.
const AI_NOT_ALLOWED_REASON = 'Enable AI data processing in your Organization settings to use AI subscriptions.'

function AiConsentGateMessage(): JSX.Element {
    return (
        <>
            {AI_NOT_ALLOWED_REASON}{' '}
            <Link to={urls.settings('organization-details', 'organization-ai-consent')}>Manage AI data processing</Link>
        </>
    )
}

// Concrete starter prompts — each one maps cleanly to a flat HogQL pattern the
// planner already knows (see PLAN_GENERATION_PROMPT reference patterns). Click
// populates the textarea verbatim so users can tweak rather than start cold.
const AI_PROMPT_EXAMPLES: { label: string; prompt: string }[] = [
    {
        label: 'Top events this week',
        prompt: 'Top 5 events by volume in the last 7 days, with counts and unique users for each.',
    },
    {
        label: 'Daily pageviews',
        prompt: 'Daily count of $pageview events for the last 14 days. Call out any day that spiked above 50% of the surrounding average.',
    },
    {
        label: 'Week-over-week growth',
        prompt: 'For the top 10 events by volume, compare this week vs last week and rank by growth rate. Flag any event that more than doubled or halved.',
    },
    {
        label: 'Peak hours',
        prompt: 'Hourly distribution of $pageview events in the last 7 days. Identify the busiest 2-hour window and how it compares to the quietest.',
    },
]
import { subscriptionsLogic } from '../subscriptionsLogic'
import {
    bysetposOptions,
    frequencyOptionsPlural,
    frequencyOptionsSingular,
    getAiSubscriptionGate,
    getNextDeliveryDate,
    intervalOptions,
    monthlyWeekdayOptions,
    targetTypeOptions,
    timeOptions,
    weekdayOptions,
    WEEKDAYS,
} from '../utils'

interface EditSubscriptionProps {
    id: number | 'new'
    insightShortId?: InsightShortId
    dashboard?: DashboardType<any> | null
    onCancel: () => void
    onDelete: () => void
}

export function EditSubscription({
    id,
    insightShortId,
    dashboard,
    onCancel,
    onDelete,
}: EditSubscriptionProps): JSX.Element {
    const dashboardId = dashboard?.id
    const logicProps = {
        id,
        insightShortId,
        dashboardId,
    }
    const logic = subscriptionLogic(logicProps)
    const subscriptionslogic = subscriptionsLogic({
        insightShortId,
        dashboardId,
    })

    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { subscription, subscriptionLoading, isSubscriptionSubmitting, subscriptionChanged, summaryQuota } =
        useValues(logic)
    const { previewLoading, previewError, previewImageUrl } = useValues(logic)
    const { resetSubscription, generatePreview } = useActions(logic)
    const { preflight, siteUrlMisconfigured } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { deleteSubscription } = useActions(subscriptionslogic)
    const { slackIntegrations, integrations } = useValues(integrationsLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const aiSubscriptionsEnabled = useFeatureFlag('SUBSCRIPTION_AI_PROMPT')

    const emailDisabled = !preflight?.email_service_available
    const isAiPrompt = subscription?.content_type === 'ai_prompt'
    // Parent-less = reached from the top-level /subscriptions page, not the kebab
    // modal on an insight/dashboard. There's nothing to snapshot here, so AI report
    // is the only valid content type — hide the snapshot/AI toggle entirely.
    const isParentless = !insightShortId && !dashboardId
    const availableFrequencyOptions = subscription?.interval === 1 ? frequencyOptionsSingular : frequencyOptionsPlural

    // For new subscriptions, show InsightSelector immediately (useEffect will auto-select)
    // For editing, wait until subscription data has loaded from API (target_type exists)
    // We check target_type instead of dashboard_export_insights because old subscriptions
    // may have no insights selected yet
    const isEditing = id !== 'new'
    const aiGate = getAiSubscriptionGate({
        isAiPrompt,
        isParentless,
        isEditing,
        aiConsentApproved: Boolean(currentOrganization?.is_ai_data_processing_approved),
        isCloud: Boolean(preflight?.cloud),
        isDebug: Boolean(preflight?.is_debug),
        aiFlagEnabled: Boolean(aiSubscriptionsEnabled),
    })
    const subscriptionLoaded = !!subscription?.target_type
    const selectionReady = !isEditing || subscriptionLoaded

    const _onDelete = (): void => {
        if (isEditing) {
            deleteSubscription(id)
            onDelete()
        }
    }

    const formatter = new Intl.DateTimeFormat('en-US', { timeZoneName: 'shortGeneric' })
    const parts = formatter.formatToParts(new Date())
    const currentTimezone = parts?.find((part) => part.type === 'timeZoneName')?.value
    const nextDeliveryDate = subscription ? getNextDeliveryDate(subscription) : null

    return (
        <Form
            logic={subscriptionLogic}
            props={logicProps}
            formKey="subscription"
            enableFormOnSubmit
            className="flex flex-1 flex-col min-h-0"
        >
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    <LemonButton icon={<IconChevronLeft />} onClick={onCancel} size="xsmall" />

                    <h3>{id === 'new' ? 'New' : 'Edit '} Subscription</h3>
                </div>
            </LemonModal.Header>

            <LemonModal.Content className="deprecated-space-y-2 flex-1 min-h-0">
                {!subscription ? (
                    subscriptionLoading ? (
                        <div className="deprecated-space-y-4">
                            <LemonSkeleton className="w-1/2 h-4" />
                            <LemonSkeleton.Row />
                            <LemonSkeleton className="w-1/2 h-4" />
                            <LemonSkeleton.Row />
                            <LemonSkeleton className="w-1/2 h-4" />
                            <LemonSkeleton.Row />
                        </div>
                    ) : (
                        <div className="p-4 text-center">
                            <h2>Not found</h2>
                            <p>This subscription could not be found. It may have been deleted.</p>
                        </div>
                    )
                ) : (
                    <>
                        {subscription?.created_by ? (
                            <UserActivityIndicator
                                at={subscription.created_at}
                                by={subscription.created_by}
                                prefix="Created"
                                className="mb-4"
                            />
                        ) : null}

                        {siteUrlMisconfigured && (
                            <LemonBanner type="warning">
                                <>
                                    Your <code>SITE_URL</code> environment variable seems misconfigured. Your{' '}
                                    <code>SITE_URL</code> is set to{' '}
                                    <b>
                                        <code>{preflight?.site_url}</code>
                                    </b>{' '}
                                    but you're currently browsing this page from{' '}
                                    <b>
                                        <code>{window.location.origin}</code>
                                    </b>
                                    . <br />
                                    If this value is not configured correctly PostHog may be unable to correctly send
                                    Subscriptions.{' '}
                                    <Link
                                        to="https://posthog.com/docs/configuring-posthog/environment-variables?utm_medium=in-product&utm_campaign=subcriptions-system-status-site-url-misconfig"
                                        target="_blank"
                                        targetBlankIcon
                                    >
                                        Learn more
                                    </Link>
                                </>
                            </LemonBanner>
                        )}

                        <div className="flex gap-4 items-end">
                            <LemonField className="flex-auto" name="title" label="Name">
                                <LemonInput placeholder="e.g. Weekly team report" />
                            </LemonField>
                            <LemonField name="enabled" className="pb-2">
                                {({ value, onChange }) => (
                                    <LemonCheckbox
                                        checked={value !== false}
                                        onChange={onChange}
                                        data-attr="subscription-enabled"
                                        label="Enabled"
                                    />
                                )}
                            </LemonField>
                        </div>

                        {dashboard?.tiles && selectionReady && (
                            <LemonField name="dashboard_export_insights" label="Insights to include">
                                {({ value, onChange }) => (
                                    <InsightSelector
                                        tiles={dashboard.tiles}
                                        selectedInsightIds={value ?? []}
                                        onChange={onChange}
                                        // After auto-selecting default insights, reset the form's "changed"
                                        // state so that auto-selection alone doesn't trigger the
                                        // "unsaved changes" warning when leaving. We merge the selected IDs
                                        // into the subscription to preserve the auto-selected values.
                                        onDefaultsApplied={(selectedIds) =>
                                            resetSubscription({
                                                ...subscription,
                                                dashboard_export_insights: selectedIds,
                                            })
                                        }
                                    />
                                )}
                            </LemonField>
                        )}

                        {aiGate.showContentTypeToggle && (
                            <LemonField name="content_type" label="What to send">
                                {({ value, onChange }) => (
                                    <LemonSegmentedButton
                                        value={value}
                                        onChange={onChange}
                                        fullWidth
                                        options={[
                                            {
                                                value: 'insight',
                                                label: 'Insight or dashboard snapshot',
                                            },
                                            {
                                                value: 'ai_prompt',
                                                label: 'AI report (beta)',
                                                disabledReason: !aiGate.aiOptionEnabled
                                                    ? AI_NOT_ALLOWED_REASON
                                                    : undefined,
                                            },
                                        ]}
                                    />
                                )}
                            </LemonField>
                        )}

                        {aiGate.showConsentHint && (
                            <LemonBanner type="info" className="text-sm">
                                <AiConsentGateMessage />
                            </LemonBanner>
                        )}

                        {isAiPrompt ? (
                            <>
                                {aiGate.showAiFormConsentBanner && (
                                    <LemonBanner type="warning" className="text-sm">
                                        <AiConsentGateMessage />
                                    </LemonBanner>
                                )}
                                <LemonBanner type="info" className="text-sm">
                                    The AI plans up to 3 HogQL queries against your project's events and writes a
                                    markdown report. It cannot access other tables, run actions, or use prior reports as
                                    context — each delivery is independent.
                                </LemonBanner>
                                <LemonField
                                    name="prompt"
                                    label="Prompt"
                                    help="Describe what the AI should look for. The same prompt runs every time the subscription fires."
                                >
                                    {/*
                                     * Char counter is rendered natively by LemonTextArea when `maxLength` is set
                                     * (turns red at the cap), so we don't add our own. Example chips sit beneath
                                     * the textarea on their own row so they wrap cleanly without competing with
                                     * the counter for horizontal space.
                                     */}
                                    <LemonTextArea
                                        placeholder="e.g. Which events grew the most week-over-week? Highlight any unusual spikes."
                                        minRows={4}
                                        maxLength={AI_PROMPT_CHAR_LIMIT}
                                    />
                                </LemonField>
                                <div className="flex flex-col gap-1">
                                    <span className="text-xs text-secondary">Try one of these prompts:</span>
                                    <div className="flex flex-wrap gap-1">
                                        {AI_PROMPT_EXAMPLES.map((example) => (
                                            <LemonButton
                                                key={example.label}
                                                size="xsmall"
                                                type="secondary"
                                                onClick={() =>
                                                    logic.actions.setSubscriptionValue('prompt', example.prompt)
                                                }
                                            >
                                                {example.label}
                                            </LemonButton>
                                        ))}
                                    </div>
                                </div>
                            </>
                        ) : null}

                        <LemonField name="target_type" label="Destination">
                            <LemonSelect options={targetTypeOptions} />
                        </LemonField>

                        {subscription.target_type === 'email' ? (
                            <>
                                {emailDisabled && (
                                    <LemonBanner type="error">
                                        <>
                                            Email subscriptions are not currently possible as this PostHog instance
                                            isn't{' '}
                                            <Link
                                                to="https://posthog.com/docs/self-host/configure/email"
                                                target="_blank"
                                                targetBlankIcon
                                            >
                                                configured&nbsp;to&nbsp;send&nbsp;emails&nbsp;
                                            </Link>
                                            .
                                        </>
                                    </LemonBanner>
                                )}

                                <LemonField
                                    name="target_value"
                                    label="Who do you want to subscribe"
                                    help="Enter the email addresses of the users you want to share with"
                                >
                                    {({ value, onChange }) => (
                                        <LemonInputSelect
                                            onChange={(val) => onChange(val.join(','))}
                                            value={value?.split(',').filter(Boolean)}
                                            disabled={emailDisabled}
                                            mode="multiple"
                                            allowCustomValues
                                            data-attr="subscribed-emails"
                                            options={usersLemonSelectOptions(meFirstMembers.map((x) => x.user))}
                                            loading={membersLoading}
                                            placeholder="Enter an email address"
                                        />
                                    )}
                                </LemonField>

                                <LemonField name="invite_message" label="Message" showOptional>
                                    <LemonTextArea placeholder="Your message to new subscribers (optional)" />
                                </LemonField>
                            </>
                        ) : null}

                        {subscription.target_type === 'slack' ? (
                            <>
                                {!slackIntegrations?.length ? (
                                    <SlackNotConfiguredBanner />
                                ) : (
                                    <>
                                        <LemonField name="integration_id" label="Slack connection">
                                            {({ value, onChange }) => (
                                                <IntegrationChoice
                                                    integration="slack"
                                                    value={value}
                                                    onChange={(newValue) => {
                                                        onChange(newValue)
                                                        // Only clear channel when user actively switches,
                                                        // not on initial auto-select (value is null)
                                                        if (value !== null && newValue !== value) {
                                                            logic.actions.setSubscriptionValue('target_value', '')
                                                        }
                                                    }}
                                                />
                                            )}
                                        </LemonField>

                                        {subscription.integration_id && (
                                            <LemonField
                                                name="target_value"
                                                label="Which Slack channel to send reports to"
                                                help={
                                                    <>
                                                        Private channels are only shown if you have{' '}
                                                        <Link
                                                            to="https://posthog.com/docs/webhooks/slack"
                                                            target="_blank"
                                                        >
                                                            added the PostHog Slack App
                                                        </Link>{' '}
                                                        to them. You can also paste the channel ID (e.g.{' '}
                                                        <code>C1234567890</code>) to search for channels.
                                                    </>
                                                }
                                            >
                                                {({ value, onChange }) => {
                                                    const selectedIntegration = integrations?.find(
                                                        (i) => i.id === subscription.integration_id
                                                    )
                                                    return selectedIntegration ? (
                                                        <SlackChannelPicker
                                                            value={value}
                                                            onChange={onChange}
                                                            integration={selectedIntegration}
                                                        />
                                                    ) : (
                                                        <></>
                                                    )
                                                }}
                                            </LemonField>
                                        )}
                                    </>
                                )}
                            </>
                        ) : null}

                        {subscription.target_type === 'webhook' ? (
                            <>
                                <LemonField name="target_value" label="Webhook URL">
                                    <LemonInput placeholder="https://example.com/webhooks/1234" />
                                </LemonField>
                                <div className="text-xs text-secondary mt-2">
                                    Webhooks will be called with a HTTP POST request. The webhook endpoint should
                                    respond with a healthy HTTP code (2xx).
                                </div>
                            </>
                        ) : null}

                        <div>
                            <div className="flex items-baseline justify-between w-full">
                                <LemonLabel className="mb-2">Recurrence</LemonLabel>
                                <div className="text-xs text-secondary text-right">{currentTimezone}</div>
                            </div>
                            <div className="flex gap-2 items-center rounded border p-2 flex-wrap">
                                <span>Send every</span>
                                <LemonField name="interval">
                                    <LemonSelect options={intervalOptions} />
                                </LemonField>
                                <LemonField name="frequency">
                                    <LemonSelect options={availableFrequencyOptions} />
                                </LemonField>

                                {subscription.frequency === 'weekly' && (
                                    <>
                                        <span>on</span>
                                        <LemonField name="byweekday">
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    options={weekdayOptions}
                                                    value={value ? value[0] : null}
                                                    onChange={(val) => onChange([val])}
                                                />
                                            )}
                                        </LemonField>
                                    </>
                                )}

                                {subscription.frequency === 'monthly' && (
                                    <>
                                        <span>on the</span>
                                        <LemonField name="bysetpos">
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    options={bysetposOptions}
                                                    value={value ? String(value) : null}
                                                    onChange={(val) => {
                                                        onChange(typeof val === 'string' ? parseInt(val, 10) : null)
                                                    }}
                                                />
                                            )}
                                        </LemonField>
                                        <LemonField name="byweekday">
                                            {({ value, onChange }) => {
                                                const isWeekday =
                                                    value?.length === 5 && value.every((d: string) => WEEKDAYS.has(d))
                                                const displayValue = value
                                                    ? isWeekday
                                                        ? 'weekday'
                                                        : value.length === 1
                                                          ? value[0]
                                                          : 'day'
                                                    : null

                                                return (
                                                    <LemonSelect
                                                        dropdownMatchSelectWidth={false}
                                                        options={monthlyWeekdayOptions}
                                                        value={displayValue}
                                                        onChange={(val) =>
                                                            onChange(
                                                                val === 'day'
                                                                    ? Object.values(weekdayOptions).map((v) => v.value)
                                                                    : val === 'weekday'
                                                                      ? [...WEEKDAYS]
                                                                      : [val]
                                                            )
                                                        }
                                                    />
                                                )
                                            }}
                                        </LemonField>
                                    </>
                                )}
                                <span>by</span>
                                <LemonField name="start_date">
                                    {({ value, onChange }) => (
                                        <LemonSelect
                                            options={timeOptions}
                                            value={dayjs(value).hour().toString()}
                                            onChange={(val) => {
                                                onChange(
                                                    dayjs()
                                                        .hour(typeof val === 'string' ? parseInt(val, 10) : 0)
                                                        .minute(0)
                                                        .second(0)
                                                        .toISOString()
                                                )
                                            }}
                                        />
                                    )}
                                </LemonField>
                            </div>
                            {nextDeliveryDate && (
                                <div className="text-xs text-secondary mt-1">
                                    Next delivery: {dayjs(nextDeliveryDate).format('ddd, MMM D [at] HH:mm')}
                                </div>
                            )}
                        </div>

                        {/*
                         * AI-prompt subscriptions are themselves an LLM-generated report —
                         * appending an insight-style "automatic AI summary" on top would be
                         * a summary of a summary. Hide the toggle entirely for AI subs.
                         */}
                        {!isAiPrompt && (
                            <FlaggedFeature flag={FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS}>
                                <LemonField name="summary_enabled">
                                    {({ value, onChange }) => (
                                        <AIConsentPopoverWrapper>
                                            <LemonSwitch
                                                checked={value}
                                                onChange={onChange}
                                                bordered
                                                label="Include an automatic AI summary"
                                                fullWidth
                                                disabledReason={
                                                    !dataProcessingAccepted && !value
                                                        ? 'Your organization needs to approve AI data processing before enabling AI summaries'
                                                        : summaryQuota?.at_limit && !value
                                                          ? `Plan limit reached (${summaryQuota.limit} active AI summaries). See details below.`
                                                          : undefined
                                                }
                                            />
                                        </AIConsentPopoverWrapper>
                                    )}
                                </LemonField>

                                {summaryQuota?.at_limit &&
                                    !subscription.summary_enabled &&
                                    summaryQuota.limit !== null && (
                                        <UsageLimitPaywall
                                            title="AI summary limit reached"
                                            description="Disable an existing AI summary or upgrade your plan to add more."
                                            limit={summaryQuota.limit}
                                            currentUsage={summaryQuota.active_count}
                                            unit="active AI summaries on your plan"
                                        />
                                    )}

                                {subscription.summary_enabled && (
                                    <FlaggedFeature flag={FEATURE_FLAGS.SUBSCRIPTION_AI_SUMMARY_PROMPT_GUIDE}>
                                        <LemonField
                                            name="summary_prompt_guide"
                                            label="Context for the AI summary"
                                            showOptional
                                        >
                                            <LemonTextArea
                                                placeholder="e.g. This is a daily revenue health check - focus on revenue drop-off and churn signals"
                                                maxLength={500}
                                            />
                                        </LemonField>
                                    </FlaggedFeature>
                                )}
                            </FlaggedFeature>
                        )}

                        {insightShortId && (
                            <div>
                                <LemonLabel className="mb-2">Preview</LemonLabel>
                                <div className="border rounded p-2">
                                    <LemonButton
                                        type="secondary"
                                        onClick={generatePreview}
                                        loading={previewLoading}
                                        disabled={previewLoading}
                                        size="small"
                                    >
                                        Generate preview
                                    </LemonButton>

                                    {previewError && (
                                        <LemonBanner type="error" className="mt-2">
                                            {previewError}
                                        </LemonBanner>
                                    )}

                                    {previewImageUrl && (
                                        <div className="mt-2 border rounded">
                                            <img
                                                src={previewImageUrl}
                                                alt="Subscription export preview"
                                                className="w-full"
                                            />
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </>
                )}
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1">
                    {subscription && id !== 'new' && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={_onDelete}
                            disabled={subscriptionLoading}
                        >
                            Delete subscription
                        </LemonButton>
                    )}
                </div>
                <LemonButton type="secondary" onClick={onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={isSubscriptionSubmitting}
                    disabled={!subscriptionChanged || subscriptionLoading || aiGate.submitBlocked}
                >
                    {id === 'new' ? 'Create subscription' : 'Save'}
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
