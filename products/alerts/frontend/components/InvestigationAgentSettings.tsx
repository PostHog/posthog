import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'

interface InvestigationAgentSettingsProps {
    alertForm: AlertFormType
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function InvestigationAgentSettings({
    alertForm,
    onSetAlertFormValue,
}: InvestigationAgentSettingsProps): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <div className="flex items-center gap-1">
                <h4 className="m-0">Investigation agent</h4>
                <Tooltip
                    title="An optional AI agent that investigates anomaly fires against this insight's own data. It runs read-only HogQL queries, looks at the metric chart, and writes its findings to a notebook linked from the alert history. You can also have it gate notifications so false positives don't page you."
                    placement="right"
                    delayMs={0}
                >
                    <IconInfo />
                </Tooltip>
            </div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                <LemonCheckbox
                    data-attr="alertForm-investigation-agent-enabled"
                    checked={!!alertForm.investigation_agent_enabled}
                    onChange={(checked) => onSetAlertFormValue('investigation_agent_enabled', checked)}
                    label={
                        <span className="flex items-center gap-1">
                            Run investigation agent when this alert fires
                            <Tooltip
                                title="On the transition to firing, an agent validates the anomaly with read-only queries, writes a notebook with its findings, and links it from the alert check history. Runs once per transition."
                                placement="right"
                                delayMs={0}
                            >
                                <IconInfo />
                            </Tooltip>
                        </span>
                    }
                />
                <LemonCheckbox
                    data-attr="alertForm-investigation-gates-notifications"
                    checked={!!alertForm.investigation_gates_notifications}
                    onChange={(checked) => onSetAlertFormValue('investigation_gates_notifications', checked)}
                    disabledReason={
                        !alertForm.investigation_agent_enabled ? 'Enable the investigation agent first' : undefined
                    }
                    label={
                        <span className="flex items-center gap-1">
                            Wait for the verdict before notifying
                            <Tooltip
                                title="Notifications are delayed ~30–90s while the agent investigates. False-positive verdicts are suppressed. A safety-net task force-fires after a few minutes if the investigation stalls, so real fires can't be silently missed."
                                placement="right"
                                delayMs={0}
                            >
                                <IconInfo />
                            </Tooltip>
                        </span>
                    }
                />
            </div>
            {alertForm.investigation_agent_enabled && alertForm.investigation_gates_notifications && (
                <div className="flex flex-wrap items-center gap-2 text-sm text-secondary">
                    <span>On inconclusive verdict</span>
                    <LemonSegmentedButton
                        size="xsmall"
                        value={alertForm.investigation_inconclusive_action ?? 'notify'}
                        onChange={(value) => onSetAlertFormValue('investigation_inconclusive_action', value)}
                        options={[
                            {
                                value: 'notify',
                                label: 'Notify',
                                tooltip: 'Safe default because an unsure agent is itself signal.',
                            },
                            { value: 'suppress', label: 'Suppress', tooltip: 'Only notify on true positives.' },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
