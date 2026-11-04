import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { DeliveryTargetsConfig, GUIDANCE_PLACEHOLDER } from '../components/EvaluationReportConfig'
import { WEEKDAY_OPTIONS, evaluationReportLogic } from '../evaluationReportLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { reportsUnavailableReason } from './evaluationSummary'

type Cadence = 'every_n' | 'daily' | 'weekly'

/** Scheduled reports in a few lines: when they arrive, where they go, and optional guidance for the agent. The step heading holds the on and off switch. */
export function EvaluationReportsPanel(): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const [guidanceOpen, setGuidanceOpen] = useState(false)
    const { evaluation, isReportableEvaluation } = useValues(llmEvaluationLogic)
    const { configDraft, configErrors, shownDestinations, reportsLoading, activeReport } = useValues(
        evaluationReportLogic({ evaluationId: props.evaluationId })
    )
    const {
        setDraftFrequency,
        setDraftScheduleCadence,
        toggleDraftScheduleWeekday,
        setDraftTriggerThreshold,
        setDraftCooldownHours,
        setDraftEmailValue,
        setDraftSlackIntegrationId,
        setDraftSlackChannelValue,
        setDraftReportPromptGuidance,
        addDraftDestination,
        removeDraftDestination,
    } = useActions(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    // The saved settings replace the draft once they load, so edits made before then would be lost.
    if (props.evaluationId !== 'new' && reportsLoading && !activeReport) {
        return (
            <div className="flex flex-col gap-3">
                <LemonSkeleton className="h-8 w-full" />
                <LemonSkeleton className="h-8 w-2/3" />
            </div>
        )
    }
    const unavailableReason = reportsUnavailableReason(evaluation, isReportableEvaluation)
    const enabled = configDraft.enabled && !unavailableReason
    const cadence: Cadence = configDraft.frequency === 'scheduled' ? configDraft.scheduleCadence : 'every_n'
    const setCadence = (next: Cadence): void => {
        if (next === 'every_n') {
            setDraftFrequency('every_n')
        } else {
            setDraftFrequency('scheduled')
            setDraftScheduleCadence(next)
        }
    }
    const error = configErrors.triggerThreshold ?? configErrors.cooldownHours

    return (
        <div className="flex flex-col gap-4">
            {unavailableReason && <p className="mb-0 text-sm text-secondary">{unavailableReason}</p>}
            {enabled && (
                <>
                    <div className="flex flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                            <span>Send a report</span>
                            <LemonSelect<Cadence>
                                size="small"
                                value={cadence}
                                onChange={setCadence}
                                options={[
                                    { value: 'every_n', label: 'every' },
                                    { value: 'daily', label: 'daily' },
                                    { value: 'weekly', label: 'weekly' },
                                ]}
                                data-attr="llma-evaluation-create-report-cadence"
                            />
                            {cadence === 'every_n' && (
                                <>
                                    <LemonInput
                                        type="number"
                                        size="small"
                                        className="w-24"
                                        value={configDraft.triggerThreshold}
                                        onChange={(value) => setDraftTriggerThreshold(Number(value))}
                                        status={configErrors.triggerThreshold ? 'danger' : undefined}
                                        aria-label="Results per report"
                                    />
                                    <span>results, at most once every</span>
                                    <LemonInput
                                        type="number"
                                        size="small"
                                        className="w-16"
                                        value={configDraft.cooldownHours}
                                        onChange={(value) => setDraftCooldownHours(Number(value))}
                                        status={configErrors.cooldownHours ? 'danger' : undefined}
                                        aria-label="Minimum hours between reports"
                                    />
                                    <span>hours</span>
                                </>
                            )}
                            {cadence === 'weekly' && (
                                <>
                                    <span>on</span>
                                    {WEEKDAY_OPTIONS.map((option) => (
                                        <LemonButton
                                            key={option.value}
                                            size="xsmall"
                                            type={
                                                configDraft.scheduleWeekdays.includes(option.value)
                                                    ? 'primary'
                                                    : 'secondary'
                                            }
                                            aria-pressed={configDraft.scheduleWeekdays.includes(option.value)}
                                            onClick={() => toggleDraftScheduleWeekday(option.value)}
                                        >
                                            {option.label}
                                        </LemonButton>
                                    ))}
                                </>
                            )}
                        </div>
                        {error && <span className="text-xs text-danger">{error}</span>}
                    </div>
                    <DeliveryTargetsConfig
                        emailValue={configDraft.emailValue}
                        onEmailChange={setDraftEmailValue}
                        slackIntegrationId={configDraft.slackIntegrationId}
                        onSlackIntegrationChange={setDraftSlackIntegrationId}
                        slackChannelValue={configDraft.slackChannelValue}
                        onSlackChannelChange={setDraftSlackChannelValue}
                        shown={shownDestinations}
                        onAdd={addDraftDestination}
                        onRemove={removeDraftDestination}
                    />
                    {guidanceOpen || configDraft.reportPromptGuidance ? (
                        <LemonTextArea
                            value={configDraft.reportPromptGuidance}
                            onChange={setDraftReportPromptGuidance}
                            placeholder={GUIDANCE_PLACEHOLDER}
                            rows={2}
                            autoFocus={guidanceOpen}
                        />
                    ) : (
                        <div>
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                icon={<IconPlus />}
                                onClick={() => setGuidanceOpen(true)}
                                data-attr="llma-evaluation-create-report-guidance"
                            >
                                Add guidance for the agent
                            </LemonButton>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
