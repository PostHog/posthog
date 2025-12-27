import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { useCallback } from 'react'

import { IconChevronLeft, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonCheckbox, LemonCollapse, LemonSelect, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { alphabet, formatDate } from 'lib/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import {
    AlertCalculationInterval,
    AlertState,
    DetectorConfig,
    DetectorType,
    InsightThresholdType,
} from '~/queries/schema/schema-general'
import { InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { SnoozeButton } from '../SnoozeButton'
import { alertFormLogic } from '../alertFormLogic'
import { alertLogic } from '../alertLogic'
import { insightAlertsLogic } from '../insightAlertsLogic'
import { AlertType } from '../types'
import { AlertDestinationSelector } from './AlertDestinationSelector'
import { BackfillPreview } from './BackfillPreview'
import { DetectorSelector } from './DetectorSelector'

function alertCalculationIntervalToLabel(interval: AlertCalculationInterval): string {
    switch (interval) {
        case AlertCalculationInterval.HOURLY:
            return 'hour'
        case AlertCalculationInterval.DAILY:
            return 'day'
        case AlertCalculationInterval.WEEKLY:
            return 'week'
        case AlertCalculationInterval.MONTHLY:
            return 'month'
    }
}

export function AlertStateTable({ alert }: { alert: AlertType }): JSX.Element | null {
    if (!alert.checks || alert.checks.length === 0) {
        return null
    }

    return (
        <div className="bg-primary p-4 mt-10 rounded-lg">
            <div className="flex flex-row gap-2 items-center mb-2">
                <h3 className="m-0">Current status: </h3>
                <AlertStateIndicator alert={alert} />
                <h3 className="m-0">
                    {alert.snoozed_until && ` until ${formatDate(dayjs(alert?.snoozed_until), 'MMM D, HH:mm')}`}
                </h3>
            </div>
            <table className="w-full table-auto border-spacing-2 border-collapse">
                <thead>
                    <tr className="text-left">
                        <th>Status</th>
                        <th className="text-right">Time</th>
                        <th className="text-right pr-4">Value</th>
                        <th>Targets notified</th>
                    </tr>
                </thead>
                <tbody>
                    {alert.checks.map((check) => (
                        <tr key={check.id}>
                            <td>{check.state}</td>
                            <td className="text-right">
                                <TZLabel time={check.created_at} />
                            </td>
                            <td className="text-right pr-4">{check.calculated_value}</td>
                            <td>{check.targets_notified ? 'Yes' : 'No'}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

interface EditAlertModalProps {
    isOpen: boolean | undefined
    alertId?: AlertType['id']
    insightId: QueryBasedInsightModel['id']
    insightShortId: InsightShortId
    onEditSuccess: (alertId?: AlertType['id'] | undefined) => void
    onClose?: () => void
    insightLogicProps?: InsightLogicProps
}

const DEFAULT_DETECTOR_CONFIG: DetectorConfig = {
    type: DetectorType.THRESHOLD,
    threshold_type: InsightThresholdType.ABSOLUTE,
    bounds: {},
} as DetectorConfig

export function EditAlertModal({
    isOpen,
    alertId,
    insightId,
    insightShortId,
    onClose,
    onEditSuccess,
    insightLogicProps,
}: EditAlertModalProps): JSX.Element {
    const _alertLogic = alertLogic({ alertId })
    const { alert, alertLoading } = useValues(_alertLogic)
    const { loadAlert } = useActions(_alertLogic)

    const _onEditSuccess = useCallback(
        (alertId: AlertType['id'] | undefined) => {
            if (alertId) {
                loadAlert()
            }
            onEditSuccess(alertId)
        },
        [loadAlert, onEditSuccess]
    )

    // Callback to refresh both alertLogic and insightAlertsLogic after backfill
    const onBackfillComplete = useCallback(() => {
        loadAlert()
        // Also refresh insightAlertsLogic to update anomaly points on the chart
        if (insightLogicProps) {
            const { loadAlerts } = insightAlertsLogic({ insightId, insightLogicProps }).actions
            loadAlerts()
        }
    }, [loadAlert, insightId, insightLogicProps])

    const formLogicProps = {
        alert,
        insightId,
        onEditSuccess: _onEditSuccess,
        insightVizDataLogicProps: insightLogicProps,
    }
    const formLogic = alertFormLogic(formLogicProps)
    const { alertForm, isAlertFormSubmitting, alertFormChanged } = useValues(formLogic)
    const { deleteAlert, snoozeAlert, clearSnooze } = useActions(formLogic)
    const { setAlertFormValue } = useActions(formLogic)

    const trendsLogic = trendsDataLogic({ dashboardItemId: insightShortId })
    const { alertSeries, isBreakdownValid, formulaNodes } = useValues(trendsLogic)

    const creatingNewAlert = alertForm.id === undefined

    // Ensure detector_config is always set
    const detectorConfig: DetectorConfig = (alertForm.detector_config ?? DEFAULT_DETECTOR_CONFIG) as DetectorConfig
    const isThresholdDetector = detectorConfig.type === DetectorType.THRESHOLD

    return (
        <LemonModal onClose={onClose} isOpen={isOpen} width={600} simple title="">
            {alertLoading ? (
                <SpinnerOverlay />
            ) : (
                <Form
                    logic={alertFormLogic}
                    props={formLogicProps}
                    formKey="alertForm"
                    enableFormOnSubmit
                    className="LemonModal__layout"
                >
                    <LemonModal.Header>
                        <div className="flex items-center gap-2">
                            <LemonButton icon={<IconChevronLeft />} onClick={onClose} size="xsmall" />
                            <h3>{creatingNewAlert ? 'New' : 'Edit '} Alert</h3>
                        </div>
                    </LemonModal.Header>

                    <LemonModal.Content>
                        <div className="deprecated-space-y-8">
                            <div className="deprecated-space-y-4">
                                <div className="flex gap-4 items-center">
                                    <LemonField className="flex-auto" name="name">
                                        <LemonInput placeholder="Alert name" data-attr="alertForm-name" />
                                    </LemonField>
                                    <LemonField name="enabled">
                                        <LemonCheckbox
                                            checked={alertForm?.enabled}
                                            data-attr="alertForm-enabled"
                                            fullWidth
                                            label="Enabled"
                                        />
                                    </LemonField>
                                </div>
                                {alert?.created_by ? (
                                    <UserActivityIndicator
                                        at={alert.created_at}
                                        by={alert.created_by}
                                        prefix="Created"
                                    />
                                ) : null}
                            </div>

                            <div className="deprecated-space-y-6">
                                <h3>Definition</h3>
                                <div className="deprecated-space-y-5">
                                    {isBreakdownValid && (
                                        <LemonBanner type="warning">
                                            For trends with breakdown, the alert will fire if any of the breakdown
                                            values breaches the threshold.
                                        </LemonBanner>
                                    )}
                                    <div className="flex gap-4 items-center">
                                        <div>When</div>
                                        <Group name={['config']}>
                                            <LemonField name="series_index" className="flex-auto">
                                                <LemonSelect
                                                    fullWidth
                                                    data-attr="alertForm-series-index"
                                                    options={
                                                        formulaNodes?.length > 0
                                                            ? formulaNodes.map(({ formula, custom_name }, index) => ({
                                                                  label: `${
                                                                      custom_name ? custom_name : 'Formula'
                                                                  } (${formula})`,
                                                                  value: index,
                                                              }))
                                                            : (alertSeries?.map(
                                                                  ({ custom_name, name, event }, index) => ({
                                                                      label: isBreakdownValid
                                                                          ? 'any breakdown value'
                                                                          : `${alphabet[index]} - ${
                                                                                custom_name ?? name ?? event
                                                                            }`,
                                                                      value: isBreakdownValid ? 0 : index,
                                                                  })
                                                              ) ?? [])
                                                    }
                                                    disabledReason={
                                                        isBreakdownValid &&
                                                        `For trends with breakdown, the alert will fire if any of the breakdown values breaches the threshold.`
                                                    }
                                                />
                                            </LemonField>
                                        </Group>
                                        <div className="text-muted-alt">triggers alert</div>
                                    </div>

                                    <div className="mt-4">
                                        <DetectorSelector
                                            config={detectorConfig}
                                            onChange={(config) => setAlertFormValue('detector_config', config)}
                                        />
                                    </div>

                                    <div className="flex gap-4 items-center">
                                        <div>Run alert every</div>
                                        <LemonField name="calculation_interval">
                                            <LemonSelect
                                                fullWidth
                                                className="w-28"
                                                data-attr="alertForm-calculation-interval"
                                                options={Object.values(AlertCalculationInterval).map((interval) => ({
                                                    label: alertCalculationIntervalToLabel(interval),
                                                    value: interval,
                                                }))}
                                            />
                                        </LemonField>
                                    </div>

                                    {!isThresholdDetector && (
                                        <BackfillPreview
                                            insightId={insightId}
                                            seriesIndex={alertForm.config.series_index ?? 0}
                                            detectorConfig={detectorConfig}
                                            alertId={alertId}
                                            onBackfillComplete={onBackfillComplete}
                                        />
                                    )}
                                </div>
                            </div>

                            <div>
                                <h3>Notification</h3>
                                <div className="flex gap-4 items-center mt-2">
                                    <div>E-mail</div>
                                    <div className="flex-auto">
                                        <MemberSelectMultiple
                                            value={alertForm.subscribed_users?.map((u) => u.id) ?? []}
                                            idKey="id"
                                            onChange={(value) => setAlertFormValue('subscribed_users', value)}
                                        />
                                    </div>
                                </div>

                                <h4 className="mt-4">CDP Destinations</h4>
                                <div className="mt-2">
                                    {alertId ? (
                                        <div className="flex flex-col">
                                            <AlertDestinationSelector alertId={alertId} />
                                        </div>
                                    ) : (
                                        <div className="text-muted-alt">
                                            Save alert first to add destinations (e.g. Slack, Webhooks)
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="deprecated-space-y-2">
                                <LemonCollapse
                                    panels={[
                                        {
                                            key: 'advanced',
                                            header: 'Advanced options',
                                            content: (
                                                <div className="space-y-4">
                                                    <LemonField name="skip_weekend">
                                                        <LemonCheckbox
                                                            checked={
                                                                (alertForm?.calculation_interval ===
                                                                    AlertCalculationInterval.DAILY ||
                                                                    alertForm?.calculation_interval ===
                                                                        AlertCalculationInterval.HOURLY) &&
                                                                alertForm?.skip_weekend
                                                            }
                                                            data-attr="alertForm-skip-weekend"
                                                            fullWidth
                                                            label="Skip checking on weekends"
                                                            disabledReason={
                                                                alertForm?.calculation_interval !==
                                                                    AlertCalculationInterval.DAILY &&
                                                                alertForm?.calculation_interval !==
                                                                    AlertCalculationInterval.HOURLY &&
                                                                'Can only skip weekend checking for hourly/daily alerts'
                                                            }
                                                        />
                                                    </LemonField>
                                                    {isThresholdDetector && (
                                                        <Group name={['config']}>
                                                            <div className="flex gap-1">
                                                                <LemonField name="check_ongoing_interval">
                                                                    <LemonCheckbox
                                                                        checked={
                                                                            alertForm?.config.check_ongoing_interval
                                                                        }
                                                                        data-attr="alertForm-check-ongoing-interval"
                                                                        fullWidth
                                                                        label="Check ongoing period"
                                                                    />
                                                                </LemonField>
                                                                <Tooltip
                                                                    title="Checks the insight value for the ongoing period (current week/month) that hasn't yet completed. Use this if you want to be alerted right away when the insight value rises/increases above threshold"
                                                                    placement="right"
                                                                    delayMs={0}
                                                                >
                                                                    <IconInfo />
                                                                </Tooltip>
                                                            </div>
                                                        </Group>
                                                    )}
                                                </div>
                                            ),
                                        },
                                    ]}
                                />
                            </div>
                        </div>

                        {alert && <AlertStateTable alert={alert} />}
                    </LemonModal.Content>

                    <LemonModal.Footer>
                        <div className="flex-1">
                            <div className="flex gap-2">
                                {!creatingNewAlert ? (
                                    <LemonButton type="secondary" status="danger" onClick={deleteAlert}>
                                        Delete alert
                                    </LemonButton>
                                ) : null}
                                {!creatingNewAlert && alert?.state === AlertState.FIRING ? (
                                    <SnoozeButton onChange={snoozeAlert} value={alert?.snoozed_until} />
                                ) : null}
                                {!creatingNewAlert && alert?.state === AlertState.SNOOZED ? (
                                    <LemonButton
                                        type="secondary"
                                        status="default"
                                        onClick={clearSnooze}
                                        tooltip={`Currently snoozed until ${formatDate(
                                            dayjs(alert?.snoozed_until),
                                            'MMM D, HH:mm'
                                        )}`}
                                    >
                                        Clear snooze
                                    </LemonButton>
                                ) : null}
                            </div>
                        </div>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isAlertFormSubmitting}
                            disabledReason={!alertFormChanged && 'No changes to save'}
                        >
                            {creatingNewAlert ? 'Create alert' : 'Save'}
                        </LemonButton>
                    </LemonModal.Footer>
                </Form>
            )}
        </LemonModal>
    )
}
