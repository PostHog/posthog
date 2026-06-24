import { useActions, useValues } from 'kea'

import { IconBell, IconCreditCard, IconPlay, IconPlus } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { AlertingChoiceCard, AlertingListToolbar, AlertingTable, AlertingWizardLayout } from 'lib/components/Alerting'
import type { AlertingWizardStep } from 'lib/components/Alerting'
import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { dayjs } from 'lib/dayjs'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import type { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import type {
    BillingAlertConfigurationStateEnumApi,
    BillingAlertEventApi,
    MetricEnumApi,
    ThresholdTypeEnumApi,
} from '~/generated/core/api.schemas'
import type { IntegrationType } from '~/types'

import {
    BILLING_ALERT_TRIGGERS,
    BillingAlertCreationView,
    BillingAlertWizardStep,
    billingAlertsLogic,
} from './billingAlertsLogic'
import type { BillingAlertConfiguration, BillingAlertDestinationKey, BillingAlertForm } from './billingAlertsLogic'

const BILLING_ALERT_WIZARD_STEPS: AlertingWizardStep<BillingAlertWizardStep>[] = [
    { key: BillingAlertWizardStep.Destination, label: 'Destination' },
    { key: BillingAlertWizardStep.Trigger, label: 'Trigger' },
    { key: BillingAlertWizardStep.Configure, label: 'Configure' },
]

const BILLING_ALERT_DESTINATIONS: {
    key: BillingAlertDestinationKey
    name: string
    description: string
    icon: string
}[] = [
    {
        key: 'slack',
        name: 'Slack',
        description: 'Post to a Slack channel when the billing alert fires, resolves, or errors.',
        icon: '/static/services/slack.png',
    },
    {
        key: 'teams',
        name: 'Microsoft Teams',
        description: 'Post to a Microsoft Teams webhook when the billing alert fires, resolves, or errors.',
        icon: '/static/services/microsoft-teams.png',
    },
    {
        key: 'webhook',
        name: 'Webhook',
        description: 'Send an HTTP request when the billing alert fires, resolves, or errors.',
        icon: '/static/services/webhook.svg',
    },
]

const BILLING_ALERT_DESTINATION_SELECT_OPTIONS = BILLING_ALERT_DESTINATIONS.map((destination) => ({
    value: destination.key,
    label: destination.name,
    icon: <img src={destination.icon} alt="" className="h-5 w-5 object-contain" />,
}))

type BillingAlertNumericFormKey =
    | 'minimum_value'
    | 'baseline_window_days'
    | 'evaluation_delay_hours'
    | 'check_interval_hours'
    | 'cooldown_hours'

const BILLING_ALERT_NUMBER_FIELDS: {
    key: BillingAlertNumericFormKey
    label: string
    min: number
    max?: number
    suffix?: string
    prefixSpend?: boolean
}[] = [
    { key: 'minimum_value', label: 'Minimum current value', min: 0, prefixSpend: true },
    { key: 'baseline_window_days', label: 'Baseline window', min: 1, max: 90, suffix: 'days' },
    { key: 'evaluation_delay_hours', label: 'Evaluation delay', min: 0, max: 72, suffix: 'hours' },
    { key: 'check_interval_hours', label: 'Check interval', min: 1, max: 24, suffix: 'hours' },
    { key: 'cooldown_hours', label: 'Cooldown', min: 0, max: 720, suffix: 'hours' },
]

function metricLabel(metric: MetricEnumApi | undefined): string {
    return metric === 'usage' ? 'Usage' : 'Spend'
}

function formatValue(value: string | null | undefined, metric: MetricEnumApi | undefined): string {
    if (value === null || value === undefined) {
        return '-'
    }
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) {
        return value
    }
    if (metric === 'spend') {
        return `$${numeric.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    }
    return numeric.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function thresholdDescription(alert: BillingAlertConfiguration): string {
    const thresholdType = alert.threshold_type ?? 'relative_increase'
    if (thresholdType === 'relative_increase') {
        return `${alert.threshold_percentage}% over ${alert.baseline_window_days}d baseline`
    }
    return `${formatValue(alert.threshold_value, alert.metric)} ${thresholdType.replaceAll('_', ' ')}`
}

function stateTagType(
    state: BillingAlertConfigurationStateEnumApi,
    enabled: boolean | undefined
): 'success' | 'danger' | 'warning' | 'muted' {
    if (!enabled) {
        return 'muted'
    }
    if (state === 'firing' || state === 'broken') {
        return 'danger'
    }
    if (state === 'errored' || state === 'snoozed') {
        return 'warning'
    }
    return 'success'
}

function stateLabel(state: BillingAlertConfigurationStateEnumApi, enabled: boolean | undefined): string {
    if (!enabled) {
        return 'Paused'
    }
    return state.replaceAll('_', ' ')
}

function destinationLabel(destinationKey: BillingAlertDestinationKey): string {
    return BILLING_ALERT_DESTINATIONS.find((destination) => destination.key === destinationKey)?.name ?? 'Destination'
}

function destinationWebhookLabel(destinationKey: BillingAlertDestinationKey): string {
    return destinationKey === 'teams' ? 'Microsoft Teams webhook URL' : 'Webhook URL'
}

function destinationDisabledReason(destinationKey: BillingAlertDestinationKey): string {
    if (destinationKey === 'slack') {
        return 'Slack connection and channel are required.'
    }
    return `Enter a valid ${destinationWebhookLabel(destinationKey).toLowerCase()}.`
}

function BillingAlertEvents({
    events,
    failed,
}: {
    events: BillingAlertEventApi[] | undefined
    failed?: boolean
}): JSX.Element {
    if (failed) {
        return <div className="p-2 text-danger">Couldn't load checks.</div>
    }
    if (!events) {
        return <Spinner />
    }
    if (events.length === 0) {
        return <div className="p-2 text-secondary">No checks recorded yet.</div>
    }
    return (
        <div className="deprecated-space-y-2">
            {events.map((event) => (
                <div key={event.id} className="flex flex-col gap-1 border-b pb-2 last:border-b-0">
                    <div className="flex gap-2 items-center">
                        <LemonTag type={event.threshold_breached ? 'danger' : 'success'}>{event.kind}</LemonTag>
                        <span className="text-secondary text-xs">
                            {dayjs(event.created_at).format('YYYY-MM-DD HH:mm')}
                        </span>
                    </div>
                    <span className="text-sm">{event.reason}</span>
                </div>
            ))}
        </div>
    )
}

export function BillingAlerts(): JSX.Element {
    const {
        alerts,
        alertsLoading,
        filteredAlerts,
        hiddenAlertCount,
        filters,
        creationView,
        eventsByAlert,
        eventsLoadFailedIds,
        alertsLoadFailed,
        canAccessBilling,
        checkingAlertId,
        updatingAlertIds,
    } = useValues(billingAlertsLogic)
    const {
        setFilters,
        resetFilters,
        setCreationView,
        updateAlert,
        deleteAlert,
        checkNow,
        loadEvents,
        openDestinationPanel,
    } = useActions(billingAlertsLogic)

    const columns: LemonTableColumns<BillingAlertConfiguration> = [
        {
            title: '',
            width: 0,
            render: function RenderIcon() {
                return <IconCreditCard className="text-2xl text-muted" />
            },
        },
        {
            title: 'Name',
            sticky: true,
            sorter: (a, b) =>
                (a.name ?? '').localeCompare(b.name ?? '', undefined, { sensitivity: 'base', numeric: true }),
            key: 'name',
            dataIndex: 'name',
            render: function RenderName(_, alert) {
                return (
                    <LemonTableLink
                        title={
                            <>
                                <span>{alert.name}</span>
                                <LemonTag size="small" type="muted" icon={<IconBell />}>
                                    Billing
                                </LemonTag>
                            </>
                        }
                        description={`${metricLabel(alert.metric)} alert: ${thresholdDescription(alert)}`}
                    />
                )
            },
        },
        createdByColumn() as LemonTableColumn<BillingAlertConfiguration, any>,
        updatedAtColumn() as LemonTableColumn<BillingAlertConfiguration, any>,
        {
            title: 'Last checked',
            width: 0,
            render: function RenderLastChecked(_, alert) {
                return alert.last_checked_at ? dayjs(alert.last_checked_at).fromNow() : 'N/A'
            },
        },
        {
            title: 'Status',
            key: 'enabled',
            sorter: (alert) => (alert.enabled ? 1 : -1),
            width: 0,
            render: function RenderStatus(_, alert) {
                return (
                    <LemonTag type={stateTagType(alert.state, alert.enabled)}>
                        {stateLabel(alert.state, alert.enabled)}
                    </LemonTag>
                )
            },
        },
        {
            width: 0,
            render: function RenderActions(_, alert) {
                const updating = updatingAlertIds.has(alert.id)
                return (
                    <More
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: alert.enabled ? 'Pause' : 'Unpause',
                                        disabledReason: updating ? 'Saving' : undefined,
                                        onClick: () => updateAlert(alert, { enabled: !alert.enabled }),
                                    },
                                    {
                                        label: 'Check now',
                                        icon: <IconPlay />,
                                        disabledReason: checkingAlertId ? 'Another alert is checking' : undefined,
                                        onClick: () =>
                                            LemonDialog.open({
                                                title: 'Check billing alert now?',
                                                description:
                                                    'This can send notifications if the alert fires, resolves, or errors.',
                                                primaryButton: {
                                                    children: 'Check now',
                                                    icon: <IconPlay />,
                                                    onClick: () => checkNow(alert),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            }),
                                    },
                                    {
                                        label: 'Add destination',
                                        icon: <IconPlus />,
                                        onClick: () => openDestinationPanel(alert.id),
                                    },
                                    {
                                        label: 'Delete',
                                        status: 'danger' as const,
                                        disabledReason: updating ? 'Deleting' : undefined,
                                        onClick: () =>
                                            LemonDialog.open({
                                                title: 'Delete billing alert?',
                                                description: `This deletes "${alert.name}" and its destinations.`,
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => deleteAlert(alert),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            }),
                                    },
                                ]}
                            />
                        }
                    />
                )
            },
        },
    ]

    if (!canAccessBilling) {
        return <div className="deprecated-space-y-4">You need billing access to manage billing alerts.</div>
    }

    if (creationView === BillingAlertCreationView.Wizard) {
        return <BillingAlertWizard />
    }

    return (
        <div className="flex flex-col gap-4" data-attr="billing-alerts-view">
            <AlertingListToolbar
                searchValue={filters.search}
                onSearchChange={(search) => setFilters({ search })}
                createdByValue={filters.createdBy}
                onCreatedByChange={(user) => setFilters({ createdBy: user?.id ?? null })}
                showPaused={filters.showPaused}
                onShowPausedChange={(showPaused) => setFilters({ showPaused: !!showPaused })}
                extraControls={
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => setCreationView(BillingAlertCreationView.Wizard)}
                    >
                        New notification
                    </LemonButton>
                }
            />

            <AlertingTable
                dataSource={filteredAlerts}
                columns={columns}
                rowKey="id"
                nouns={['billing alert', 'billing alerts']}
                loading={alertsLoading}
                emptyState={
                    alertsLoadFailed ? (
                        "Couldn't load billing alerts."
                    ) : alerts.length === 0 && !alertsLoading ? (
                        'No billing alerts found'
                    ) : (
                        <>
                            No billing alerts matching filters. <Link onClick={resetFilters}>Clear filters</Link>
                        </>
                    )
                }
                footer={
                    hiddenAlertCount > 0 ? (
                        <div className="p-3 text-secondary">
                            {hiddenAlertCount} hidden.{' '}
                            <Link
                                onClick={() => {
                                    resetFilters()
                                    setFilters({ showPaused: true })
                                }}
                            >
                                Show all
                            </Link>
                        </div>
                    ) : null
                }
                data-attr="billing-alerts-table"
                pagination={{ pageSize: 30 }}
                expandable={{
                    expandedRowRender: (alert) => (
                        <BillingAlertEvents
                            events={eventsByAlert[alert.id]}
                            failed={eventsLoadFailedIds.has(alert.id)}
                        />
                    ),
                    onRowExpand: (alert) => loadEvents(alert.id),
                }}
            />

            <BillingAlertDestinationPanel />
        </div>
    )
}

function BillingAlertWizard(): JSX.Element {
    const { wizardStep } = useValues(billingAlertsLogic)
    const { setWizardStep, resetCreation } = useActions(billingAlertsLogic)

    return (
        <AlertingWizardLayout
            steps={BILLING_ALERT_WIZARD_STEPS}
            currentStep={wizardStep}
            onStepClick={setWizardStep}
            onCancel={resetCreation}
        >
            {wizardStep === BillingAlertWizardStep.Destination && <BillingAlertDestinationStep />}
            {wizardStep === BillingAlertWizardStep.Trigger && <BillingAlertTriggerStep />}
            {wizardStep === BillingAlertWizardStep.Configure && <BillingAlertConfigureStep />}
        </AlertingWizardLayout>
    )
}

function BillingAlertDestinationStep(): JSX.Element {
    const { selectedDestinationKey } = useValues(billingAlertsLogic)
    const { selectDestination } = useActions(billingAlertsLogic)

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">Where should PostHog send it?</h2>
                <p className="text-secondary text-sm">Choose the first notification destination for this alert.</p>
            </div>
            <div className="space-y-3">
                {BILLING_ALERT_DESTINATIONS.map((destination) => (
                    <AlertingChoiceCard
                        key={destination.key}
                        icon={<img src={destination.icon} alt="" className="h-8 w-8 object-contain" />}
                        name={destination.name}
                        description={destination.description}
                        selected={selectedDestinationKey === destination.key}
                        onClick={() => selectDestination(destination.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function BillingAlertTriggerStep(): JSX.Element {
    const { selectedTriggerKey } = useValues(billingAlertsLogic)
    const { selectTrigger } = useActions(billingAlertsLogic)

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">What should trigger the alert?</h2>
                <p className="text-secondary text-sm">Choose the billing condition to monitor.</p>
            </div>
            <div className="space-y-3">
                {BILLING_ALERT_TRIGGERS.map((trigger) => (
                    <AlertingChoiceCard
                        key={trigger.key}
                        name={trigger.name}
                        description={trigger.description}
                        selected={selectedTriggerKey === trigger.key}
                        onClick={() => selectTrigger(trigger.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function BillingAlertConfigureStep(): JSX.Element {
    const { canSubmit, saving } = useValues(billingAlertsLogic)
    const { createAlert } = useActions(billingAlertsLogic)

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">Configure your alert</h2>
                <p className="text-secondary text-sm">Set the threshold and notification details.</p>
            </div>
            <div className="deprecated-space-y-4">
                <BillingAlertThresholdFields />
                <BillingAlertDestinationFields />
            </div>
            <div className="flex justify-end gap-2">
                <LemonButton
                    type="primary"
                    onClick={createAlert}
                    loading={saving}
                    disabledReason={!canSubmit ? 'Name, threshold, and destination details are required.' : undefined}
                    data-attr="create-billing-alert"
                >
                    Create alert
                </LemonButton>
            </div>
        </div>
    )
}

function BillingAlertThresholdFields(): JSX.Element {
    const { form } = useValues(billingAlertsLogic)
    const { setFormValue } = useActions(billingAlertsLogic)

    return (
        <>
            <LemonField.Pure label="Name">
                <LemonInput
                    value={form.name}
                    onChange={(name) => setFormValue('name', name)}
                    placeholder="Alert name"
                    data-attr="billing-alert-name"
                />
            </LemonField.Pure>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <LemonField.Pure label="Metric">
                    <LemonSelect
                        value={form.metric}
                        onChange={(metric) => setFormValue('metric', metric as MetricEnumApi)}
                        options={[
                            { value: 'spend', label: 'Spend' },
                            { value: 'usage', label: 'Usage' },
                        ]}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Threshold type">
                    <LemonSelect
                        value={form.threshold_type}
                        onChange={(thresholdType) =>
                            setFormValue('threshold_type', thresholdType as ThresholdTypeEnumApi)
                        }
                        options={[
                            { value: 'relative_increase', label: 'Relative increase' },
                            { value: 'absolute_value', label: 'Absolute value' },
                            { value: 'absolute_increase', label: 'Absolute increase' },
                        ]}
                    />
                </LemonField.Pure>
                {form.threshold_type === 'relative_increase' ? (
                    <LemonField.Pure label="Increase">
                        <LemonInput
                            type="number"
                            value={form.threshold_percentage}
                            onChange={(thresholdPercentage) =>
                                setFormValue('threshold_percentage', thresholdPercentage ?? 0)
                            }
                            suffix={<span>%</span>}
                            min={0}
                            data-attr="billing-alert-threshold-percentage"
                        />
                    </LemonField.Pure>
                ) : (
                    <LemonField.Pure label={form.metric === 'spend' ? 'Amount' : 'Value'}>
                        <LemonInput
                            type="number"
                            value={form.threshold_value}
                            onChange={(thresholdValue) => setFormValue('threshold_value', thresholdValue ?? undefined)}
                            prefix={form.metric === 'spend' ? <span>$</span> : undefined}
                            min={0}
                            data-attr="billing-alert-threshold-value"
                        />
                    </LemonField.Pure>
                )}
                {BILLING_ALERT_NUMBER_FIELDS.map((field) => (
                    <BillingAlertNumberField key={field.key} field={field} form={form} setFormValue={setFormValue} />
                ))}
            </div>
        </>
    )
}

function BillingAlertNumberField({
    field,
    form,
    setFormValue,
}: {
    field: (typeof BILLING_ALERT_NUMBER_FIELDS)[number]
    form: BillingAlertForm
    setFormValue: (key: keyof BillingAlertForm, value: BillingAlertForm[keyof BillingAlertForm]) => void
}): JSX.Element {
    return (
        <LemonField.Pure label={field.label}>
            <LemonInput
                type="number"
                value={form[field.key]}
                onChange={(value) => setFormValue(field.key, value ?? field.min)}
                prefix={field.prefixSpend && form.metric === 'spend' ? <span>$</span> : undefined}
                suffix={field.suffix ? <span>{field.suffix}</span> : undefined}
                min={field.min}
                max={field.max}
            />
        </LemonField.Pure>
    )
}

function BillingAlertDestinationFields(): JSX.Element {
    const { selectedDestinationKey, slackIntegrationId, slackChannel, webhookUrl } = useValues(billingAlertsLogic)
    const { setSelectedDestinationKey, setSlackIntegrationId, setSlackChannel, setWebhookUrl } =
        useActions(billingAlertsLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const slackIntegrations = integrations?.filter((integration) => integration.kind === 'slack') ?? []
    const selectedSlackIntegration = integrations?.find((integration) => integration.id === slackIntegrationId)

    return (
        <div className="deprecated-space-y-3">
            <h3 className="mb-0">Destination</h3>
            <LemonField.Pure label="Destination type">
                <LemonSelect
                    value={selectedDestinationKey}
                    onChange={(destinationKey) =>
                        setSelectedDestinationKey(destinationKey as BillingAlertDestinationKey)
                    }
                    options={BILLING_ALERT_DESTINATION_SELECT_OPTIONS}
                />
            </LemonField.Pure>

            {selectedDestinationKey === 'slack' ? (
                integrationsLoading ? (
                    <Spinner />
                ) : !slackIntegrations.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <IntegrationChoice
                            integration="slack"
                            value={slackIntegrationId ?? undefined}
                            onChange={(integrationId) => setSlackIntegrationId(integrationId)}
                        />
                        {selectedSlackIntegration ? (
                            <SlackChannelPicker
                                integration={selectedSlackIntegration as IntegrationType}
                                value={slackChannel ?? undefined}
                                onChange={setSlackChannel}
                            />
                        ) : null}
                    </div>
                )
            ) : (
                <LemonField.Pure label={destinationWebhookLabel(selectedDestinationKey)}>
                    <LemonInput
                        value={webhookUrl}
                        onChange={setWebhookUrl}
                        placeholder="https://..."
                        data-attr="billing-alert-webhook-url"
                    />
                </LemonField.Pure>
            )}
        </div>
    )
}

function BillingAlertDestinationPanel(): JSX.Element | null {
    const { destinationAlertId, selectedDestinationKey, destinationSaving, canCreateDestination } =
        useValues(billingAlertsLogic)
    const { setDestinationAlertId, createDestination } = useActions(billingAlertsLogic)

    if (!destinationAlertId) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={() => setDestinationAlertId(null)}
            title="Add destination"
            width={600}
            data-attr="billing-alert-destination"
        >
            <div className="deprecated-space-y-4">
                <BillingAlertDestinationFields />
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={createDestination}
                        loading={destinationSaving}
                        disabledReason={
                            !canCreateDestination ? destinationDisabledReason(selectedDestinationKey) : undefined
                        }
                        data-attr="create-billing-alert-destination"
                    >
                        Add {destinationLabel(selectedDestinationKey)} destination
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}
