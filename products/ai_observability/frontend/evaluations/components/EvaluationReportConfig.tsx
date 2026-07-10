import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'

import {
    COOLDOWN_HOURS_MAX,
    COOLDOWN_HOURS_MIN,
    evaluationReportLogic,
    TRIGGER_THRESHOLD_MAX,
    TRIGGER_THRESHOLD_MIN,
    WEEKDAY_OPTIONS,
} from '../evaluationReportLogic'
import type { ReportScheduleCadence, ReportScheduleWeekday } from '../evaluationReportLogic'

const GUIDANCE_PLACEHOLDER =
    "Optional guidance for the report agent. e.g. 'Focus on cost regressions across models', 'Compare latency between gpt-4o-mini and claude-sonnet', 'Keep it to 2 sections max'"

const FREQUENCY_OPTIONS = [
    { value: 'every_n' as const, label: 'Every N evaluations' },
    { value: 'scheduled' as const, label: 'On a schedule' },
]

const SCHEDULE_OPTIONS = [
    { value: 'daily' as const, label: 'Daily' },
    { value: 'weekly' as const, label: 'Weekly' },
]

/** Daily/weekly schedule controls shown when frequency is 'scheduled'. */
export function ScheduleConfig({
    cadence,
    weekdays,
    onCadenceChange,
    onWeekdayToggle,
}: {
    cadence: ReportScheduleCadence
    weekdays: ReportScheduleWeekday[]
    onCadenceChange: (value: ReportScheduleCadence) => void
    onWeekdayToggle: (value: ReportScheduleWeekday) => void
}): JSX.Element {
    return (
        <div className="space-y-3">
            <div>
                <label className="font-semibold text-sm">Schedule</label>
                <LemonSegmentedButton value={cadence} onChange={onCadenceChange} options={SCHEDULE_OPTIONS} />
            </div>
            {cadence === 'weekly' && (
                <div>
                    <label className="font-semibold text-sm">Days of the week</label>
                    <div className="flex flex-wrap gap-1 mt-1">
                        {WEEKDAY_OPTIONS.map((option) => {
                            const selected = weekdays.includes(option.value)
                            return (
                                <LemonButton
                                    key={option.value}
                                    size="small"
                                    type={selected ? 'primary' : 'secondary'}
                                    active={selected}
                                    onClick={() => onWeekdayToggle(option.value)}
                                >
                                    {option.label}
                                </LemonButton>
                            )
                        })}
                    </div>
                </div>
            )}
        </div>
    )
}

/** Threshold config shown when frequency is 'every_n' */
function ThresholdConfig({ value, onChange }: { value: number; onChange: (value: number) => void }): JSX.Element {
    return (
        <div>
            <label className="font-semibold text-sm">Evaluation count threshold</label>
            <LemonInput
                type="number"
                min={TRIGGER_THRESHOLD_MIN}
                max={TRIGGER_THRESHOLD_MAX}
                value={value}
                onChange={(val) => onChange(Number(val))}
                fullWidth
            />
            <p className="text-xs text-muted mt-1">
                A report will be generated after this many new evaluation results arrive. Checked every 5 minutes. Min{' '}
                {TRIGGER_THRESHOLD_MIN}, max {TRIGGER_THRESHOLD_MAX.toLocaleString()}.
            </p>
        </div>
    )
}

/** Cooldown config shown when frequency is 'every_n' */
function CooldownConfig({ value, onChange }: { value: number; onChange: (value: number) => void }): JSX.Element {
    return (
        <div>
            <label className="font-semibold text-sm">Minimum hours between reports</label>
            <LemonInput
                type="number"
                min={COOLDOWN_HOURS_MIN}
                max={COOLDOWN_HOURS_MAX}
                value={value}
                onChange={(val) => onChange(Number(val))}
                fullWidth
            />
            <p className="text-xs text-muted mt-1">
                After a report is generated, wait this many hours before generating another — even if the threshold is
                crossed again. Min {COOLDOWN_HOURS_MIN}, max {COOLDOWN_HOURS_MAX}.
            </p>
        </div>
    )
}

/** Shared delivery targets configuration */
function DeliveryTargetsConfig({
    emailValue,
    onEmailChange,
    slackIntegrationId,
    onSlackIntegrationChange,
    slackChannelValue,
    onSlackChannelChange,
}: {
    emailValue: string
    onEmailChange: (value: string) => void
    slackIntegrationId: number | null
    onSlackIntegrationChange: (value: number | null) => void
    slackChannelValue: string
    onSlackChannelChange: (value: string) => void
}): JSX.Element {
    const { slackIntegrations, integrations } = useValues(integrationsLogic)
    const selectedIntegration =
        slackIntegrationId !== null ? integrations?.find((i) => i.id === slackIntegrationId) : undefined

    return (
        <>
            <div>
                <label className="font-semibold text-sm">Email recipients</label>
                <LemonInput
                    value={emailValue}
                    onChange={onEmailChange}
                    placeholder="email1@example.com, email2@example.com"
                    fullWidth
                />
                <p className="text-xs text-muted mt-1">Comma-separated email addresses</p>
            </div>
            <div>
                <label className="font-semibold text-sm">Slack channel</label>
                {!slackIntegrations?.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <div className="space-y-2">
                        <IntegrationChoice
                            integration="slack"
                            value={slackIntegrationId ?? undefined}
                            onChange={(newValue) => {
                                if (newValue !== slackIntegrationId) {
                                    onSlackChannelChange('')
                                }
                                onSlackIntegrationChange(newValue)
                            }}
                        />
                        {selectedIntegration && (
                            <SlackChannelPicker
                                value={slackChannelValue}
                                onChange={(val) => onSlackChannelChange(val || '')}
                                integration={selectedIntegration}
                            />
                        )}
                    </div>
                )}
            </div>
        </>
    )
}

/** Shared form body used by both the create-evaluation and edit-existing-evaluation paths.
 * All state is backed by `evaluationReportLogic.configDraft` keyed by evaluationId. */
function ReportFormFields({ evaluationId }: { evaluationId: string }): JSX.Element {
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId }))
    const {
        setDraftFrequency,
        setDraftScheduleCadence,
        toggleDraftScheduleWeekday,
        setDraftEmailValue,
        setDraftSlackIntegrationId,
        setDraftSlackChannelValue,
        setDraftReportPromptGuidance,
        setDraftTriggerThreshold,
        setDraftCooldownHours,
    } = useActions(evaluationReportLogic({ evaluationId }))

    return (
        <div className="space-y-4 mt-4">
            <div>
                <label className="font-semibold text-sm">Frequency</label>
                <LemonSegmentedButton
                    value={configDraft.frequency}
                    onChange={setDraftFrequency}
                    options={FREQUENCY_OPTIONS}
                    fullWidth
                />
            </div>
            {configDraft.frequency === 'every_n' && (
                <>
                    <ThresholdConfig value={configDraft.triggerThreshold} onChange={setDraftTriggerThreshold} />
                    <CooldownConfig value={configDraft.cooldownHours} onChange={setDraftCooldownHours} />
                </>
            )}
            {configDraft.frequency === 'scheduled' && (
                <ScheduleConfig
                    cadence={configDraft.scheduleCadence}
                    weekdays={configDraft.scheduleWeekdays}
                    onCadenceChange={setDraftScheduleCadence}
                    onWeekdayToggle={toggleDraftScheduleWeekday}
                />
            )}
            <DeliveryTargetsConfig
                emailValue={configDraft.emailValue}
                onEmailChange={setDraftEmailValue}
                slackIntegrationId={configDraft.slackIntegrationId}
                onSlackIntegrationChange={setDraftSlackIntegrationId}
                slackChannelValue={configDraft.slackChannelValue}
                onSlackChannelChange={setDraftSlackChannelValue}
            />
            <div>
                <label className="font-semibold text-sm">Report agent guidance (optional)</label>
                <LemonTextArea
                    value={configDraft.reportPromptGuidance}
                    onChange={setDraftReportPromptGuidance}
                    placeholder={GUIDANCE_PLACEHOLDER}
                    rows={3}
                />
                <p className="text-xs text-muted mt-1">
                    Steers the agent's focus, section choices, or scope. Appended to the base prompt.
                </p>
            </div>
        </div>
    )
}

/** Inline config shown during new evaluation creation */
function PendingReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId }))
    const { setDraftEnabled } = useActions(evaluationReportLogic({ evaluationId }))

    return (
        <div className="bg-bg-light border rounded p-6">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-lg font-semibold mb-1">Scheduled reports</h3>
                    <p className="text-muted text-sm">
                        AI-generated analysis of evaluation results. Reports are always available in the Reports tab.
                        Optionally add email or Slack to get notified.
                    </p>
                </div>
                <LemonSwitch
                    checked={configDraft.enabled}
                    onChange={setDraftEnabled}
                    bordered
                    label={configDraft.enabled ? 'Enabled' : 'Disabled'}
                />
            </div>
            <ReportFormFields evaluationId={evaluationId} />
        </div>
    )
}

/** Toggle-based report management for existing evaluations.
 * The "Save changes" button at the top of the evaluation page persists any
 * draft updates — see llmEvaluationLogic.saveEvaluation, which forwards
 * the draft to persistReportDraft. Disabling the toggle is a staged config
 * update that sets enabled=false, preserving the report config row. */
function ExistingReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    const logic = evaluationReportLogic({ evaluationId })
    const { activeReport, reportsLoading, configDraft, isConfigDirty } = useValues(logic)
    const { setDraftEnabled } = useActions(logic)

    const isEnabled = configDraft.enabled

    return (
        <div className="bg-bg-light border rounded p-6">
            <div className="flex items-center justify-between mb-4">
                <div className="space-y-1">
                    <div className="flex items-center gap-2">
                        <h3 className="text-lg font-semibold m-0">Scheduled reports</h3>
                        {isConfigDirty && <LemonTag type="warning">Unsaved changes</LemonTag>}
                    </div>
                    <p className="text-muted text-sm m-0">
                        AI-generated analysis of evaluation results. Reports are always available in the Reports tab.
                        Optionally add email or Slack to get notified.
                    </p>
                </div>
                <LemonSwitch
                    checked={isEnabled}
                    onChange={setDraftEnabled}
                    bordered
                    loading={reportsLoading}
                    label={isEnabled ? 'Enabled' : 'Disabled'}
                />
            </div>

            {reportsLoading && !activeReport ? (
                <div className="space-y-3 mt-4">
                    <LemonSkeleton className="h-9 w-full" />
                    <LemonSkeleton className="h-9 w-full" />
                    <LemonSkeleton className="h-20 w-full" />
                </div>
            ) : activeReport ? (
                <>
                    <ReportFormFields evaluationId={evaluationId} />
                    {configDraft.frequency === 'every_n'
                        ? (() => {
                              const cooldownHours = configDraft.cooldownHours
                              return (
                                  <div className="text-sm text-muted mt-4">
                                      {configDraft.enabled ? 'A report' : 'When enabled, a report'} will be generated
                                      when {configDraft.triggerThreshold} new evaluation results arrive, at most once
                                      every {cooldownHours} {cooldownHours === 1 ? 'hour' : 'hours'}. Checked every 5
                                      minutes.
                                  </div>
                              )
                          })()
                        : activeReport.next_delivery_date && (
                              <div className="text-sm text-muted mt-4">
                                  Next delivery: {new Date(activeReport.next_delivery_date).toLocaleString()}
                              </div>
                          )}
                    <p className="text-xs text-muted m-0 mt-2">Generated reports appear in the Reports tab.</p>
                </>
            ) : (
                <ReportFormFields evaluationId={evaluationId} />
            )}
        </div>
    )
}

export function EvaluationReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    if (evaluationId === 'new') {
        return <PendingReportConfig evaluationId={evaluationId} />
    }
    return <ExistingReportConfig evaluationId={evaluationId} />
}
