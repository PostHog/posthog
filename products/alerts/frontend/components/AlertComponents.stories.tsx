import type { Meta, StoryObj } from '@storybook/react'
import { kea, path, useActions, useValues } from 'kea'
import { Form, forms } from 'kea-forms'
import { useEffect, useState } from 'react'

import type { LemonSegmentedButtonOption, LemonSelectOptions } from '@posthog/lemon-ui'
import { LemonCheckbox, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { useStorybookMocks } from '~/mocks/browser'
import { AlertCalculationInterval } from '~/queries/schema/schema-general'
import { IntegrationType } from '~/types'

import { alertNotificationLogic } from 'products/alerts/frontend/logic/alertNotificationLogic'
import type { ScheduleRestriction } from 'products/alerts/frontend/types'
import { InlineAlertNotifications } from 'products/alerts/frontend/views/InlineAlertNotifications'

import { AlertAdvancedOptions } from './AlertAdvancedOptions'
import { AlertDefinitionRow, AlertNextEvaluationStatus, AlertTimezoneNotice } from './AlertDefinition'
import { AlertEditor, AlertEditorFormDetails, AlertEditorLoading, AlertEditorSection } from './AlertEditor'
import {
    AlertEvaluationHistoryChart,
    AlertEvaluationHistoryPoint,
    AlertEvaluationThreshold,
} from './AlertEvaluationHistoryChart'
import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
} from './AlertNotificationDestinationEditor'
import { QuietHoursFields } from './QuietHoursFields'

const alertEditorStoryLogic = kea([
    path(['products', 'alerts', 'components', 'AlertComponents', 'story']),
    forms({
        alertForm: {
            defaults: {
                name: 'Error rate alert',
                enabled: true,
            },
            submit: () => Promise.resolve(),
        },
    }),
])

function EditorStory(): JSX.Element {
    const { alertForm } = useValues(alertEditorStoryLogic)
    const [lastAction, setLastAction] = useState('No action selected')

    return (
        <div className="max-w-3xl border rounded bg-surface-primary">
            <Form logic={alertEditorStoryLogic} formKey="alertForm" enableFormOnSubmit>
                <AlertEditor
                    title="Edit alert"
                    description="Get notified when a condition is met."
                    onBack={() => setLastAction('Selected back')}
                    isEditing
                    isSubmitting={false}
                    hasChanges
                    onSubmitAttempted={() => setLastAction('Saved alert')}
                    leadingActions={
                        <LemonButton type="secondary" onClick={() => setLastAction('Selected delete')}>
                            Delete alert
                        </LemonButton>
                    }
                >
                    <div className="space-y-6">
                        <AlertEditorFormDetails
                            enabled={{ checked: alertForm.enabled }}
                            activity={<p className="text-muted text-sm m-0">Created by Story User</p>}
                        />
                        <AlertEditorSection
                            title="Definition"
                            description="Product-specific alert conditions render inside shared sections."
                        >
                            <div className="border rounded p-3 text-sm">Alert when the error rate exceeds 5%.</div>
                        </AlertEditorSection>
                        <AlertEditorSection title="Notifications">
                            <div className="border rounded p-3 text-sm">Send a notification to #alerts.</div>
                        </AlertEditorSection>
                        <p className="text-muted m-0">{lastAction}</p>
                    </div>
                </AlertEditor>
            </Form>
        </div>
    )
}

function EditorLoadingStory(): JSX.Element {
    return (
        <div className="max-w-3xl overflow-hidden rounded border bg-surface-primary">
            <AlertEditorLoading title="Edit alert" onBack={() => {}} />
        </div>
    )
}

type DefinitionMode = 'above' | 'below'

const DEFINITION_MODE_OPTIONS: LemonSegmentedButtonOption<DefinitionMode>[] = [
    { label: 'Above', value: 'above' },
    { label: 'Below', value: 'below' },
]

function DefinitionStory(): JSX.Element {
    const [mode, setMode] = useState<DefinitionMode>('above')
    const [threshold, setThreshold] = useState('100')

    return (
        <div className="max-w-2xl space-y-5 border rounded bg-surface-primary p-4">
            <AlertDefinitionRow label="Alert if event count is">
                <LemonSegmentedButton value={mode} options={DEFINITION_MODE_OPTIONS} onChange={setMode} size="small" />
                <LemonInput value={threshold} onChange={setThreshold} className="w-24" />
            </AlertDefinitionRow>
            <div className="space-y-2">
                <AlertDefinitionRow label="Evaluate every">
                    <span className="font-semibold">15 minutes</span>
                </AlertDefinitionRow>
                <AlertNextEvaluationStatus>July 17, 2026 at 12:15 PM</AlertNextEvaluationStatus>
                <AlertTimezoneNotice timezone="America/Toronto" settingsUrl="#project-settings" />
            </div>
        </div>
    )
}

function AdvancedOptionsStory(): JSX.Element {
    const [skipWeekends, setSkipWeekends] = useState(true)
    const [quietHours, setQuietHours] = useState(true)
    const enabledCount = Number(skipWeekends) + Number(quietHours)

    return (
        <div className="max-w-2xl border rounded bg-surface-primary p-4">
            <AlertAdvancedOptions enabledCount={enabledCount}>
                <LemonCheckbox checked={skipWeekends} onChange={setSkipWeekends} label="Skip weekend evaluations" />
                <LemonCheckbox
                    checked={quietHours}
                    onChange={setQuietHours}
                    label="Pause notifications during quiet hours"
                />
            </AlertAdvancedOptions>
        </div>
    )
}

type StoryNotificationType = 'slack' | 'webhook'

const NOTIFICATION_TYPE_OPTIONS: LemonSelectOptions<StoryNotificationType> = [
    { label: 'Slack', value: 'slack' },
    { label: 'Webhook', value: 'webhook' },
]

function NotificationsStory(): JSX.Element {
    const [selectedType, setSelectedType] = useState<StoryNotificationType>('webhook')
    const [urlValue, setUrlValue] = useState('https://example.com/alerts')
    const [slackChannelValue, setSlackChannelValue] = useState<string | null>(null)
    const [existingDestinations, setExistingDestinations] = useState<AlertNotificationDestinationView[]>([
        {
            key: 'existing-slack',
            title: 'Slack: #product-alerts',
            tags: [{ label: 'Active', type: 'success' }],
            viewAction: { kind: 'button', label: 'View', url: '#destination' },
            onDelete: () => setExistingDestinations([]),
        },
    ])
    const [pendingDestinations, setPendingDestinations] = useState<PendingAlertNotificationDestinationView[]>([
        {
            key: 'pending-webhook',
            title: 'Webhook',
            detail: 'https://example.com/pending',
            onRemove: () => setPendingDestinations([]),
        },
    ])

    const addDestination = (): void => {
        if (selectedType !== 'webhook' || !urlValue) {
            return
        }
        setPendingDestinations((destinations) => [
            ...destinations,
            {
                key: `pending-${destinations.length}`,
                title: 'Webhook',
                detail: urlValue,
                onRemove: () => setPendingDestinations([]),
            },
        ])
        setUrlValue('')
    }

    let addDisabledReason: string | undefined
    if (selectedType === 'slack') {
        addDisabledReason = 'Connect Slack first'
    } else if (!urlValue) {
        addDisabledReason = 'Enter a webhook URL'
    }

    return (
        <div className="max-w-2xl border rounded bg-surface-primary p-4">
            <AlertNotificationDestinationEditor
                description="Each destination receives alert state changes."
                destinations={{
                    showExisting: true,
                    existingLoading: false,
                    existing: existingDestinations,
                    pending: pendingDestinations,
                }}
                notificationType={{
                    options: NOTIFICATION_TYPE_OPTIONS,
                    value: selectedType,
                    onChange: setSelectedType,
                }}
                slack={{
                    notificationType: 'slack',
                    integrationsLoading: false,
                    integrationsFailed: false,
                    onRetryIntegrations: () => {},
                    integrations: [],
                    channelValue: slackChannelValue,
                    onChannelValueChange: setSlackChannelValue,
                }}
                url={
                    selectedType === 'webhook'
                        ? {
                              input: { placeholder: 'https://example.com/webhook' },
                              value: urlValue,
                              onChange: setUrlValue,
                          }
                        : undefined
                }
                add={{ onClick: addDestination, disabledReason: addDisabledReason }}
            />
        </div>
    )
}

const STORY_SLACK_WORKSPACES: IntegrationType[] = [
    {
        id: 1,
        kind: 'slack',
        display_name: 'PostHog',
        icon_url: '/static/services/slack.png',
        config: { team: { id: 'T11111', name: 'PostHog' } },
        created_at: '2026-01-01T00:00:00Z',
    },
    {
        id: 2,
        kind: 'slack',
        display_name: 'Acme Workspace',
        icon_url: '/static/services/slack.png',
        config: { team: { id: 'T99999', name: 'Acme Workspace' } },
        created_at: '2026-01-01T00:00:00Z',
    },
]

const STORY_SLACK_CHANNELS: Record<string, { id: string; name: string }[]> = {
    '1': [
        { id: 'C100', name: 'alerts' },
        { id: 'C101', name: 'general' },
    ],
    '2': [
        { id: 'C200', name: 'acme-alerts' },
        { id: 'C201', name: 'acme-eng' },
    ],
}

const STORY_EXISTING_HOG_FUNCTIONS = [
    {
        id: 'hf1',
        type: 'internal_destination',
        name: 'Alert: Slack #alerts',
        description: '',
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        enabled: true,
        hog: '',
        template_id: 'template-slack',
        inputs: {
            slack_workspace: { value: 1 },
            channel: { value: 'C100' },
        },
    },
    {
        id: 'hf2',
        type: 'internal_destination',
        name: 'Alert: Slack #acme-alerts',
        description: '',
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        enabled: true,
        hog: '',
        template_id: 'template-slack',
        inputs: {
            slack_workspace: { value: 2 },
            channel: { value: 'C200' },
        },
    },
]

function MultipleSlackWorkspacesStory(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/integrations': { results: STORY_SLACK_WORKSPACES, count: 2 },
            '/api/environments/:team_id/integrations/:id/channels': ({ params, request }) => {
                const channelId = new URL(request.url).searchParams.get('channel_id')
                const allChannels = (STORY_SLACK_CHANNELS[String(params.id)] ?? []).map((channel) => ({
                    ...channel,
                    is_private: false,
                    is_ext_shared: false,
                    is_member: true,
                }))
                const channels = channelId ? allChannels.filter((channel) => channel.id === channelId) : allChannels
                return [200, { channels, lastRefreshedAt: '2026-01-01T00:00:00Z' }]
            },
            '/api/environments/:team_id/hog_functions': {
                results: STORY_EXISTING_HOG_FUNCTIONS,
                count: STORY_EXISTING_HOG_FUNCTIONS.length,
            },
        },
    })

    // Preselect a workspace + channel so the picker doesn't open empty.
    const { setSelectedSlackIntegrationId, setSlackChannelValue } = useActions(
        alertNotificationLogic({ alertId: 'alert-1' })
    )
    useEffect(() => {
        setSelectedSlackIntegrationId(2)
        setSlackChannelValue('C201|#acme-eng')
    }, [setSelectedSlackIntegrationId, setSlackChannelValue])

    return (
        <div className="max-w-2xl border rounded bg-surface-primary p-4">
            <InlineAlertNotifications alertId="alert-1" />
        </div>
    )
}

function QuietHoursStory(): JSX.Element {
    const [scheduleRestriction, setScheduleRestriction] = useState<ScheduleRestriction | null>({
        blocked_windows: [{ start: '22:00', end: '07:00' }],
    })

    return (
        <div className="max-w-2xl border rounded bg-surface-primary p-4">
            <QuietHoursFields
                scheduleRestriction={scheduleRestriction}
                onChange={setScheduleRestriction}
                teamTimezone="America/Toronto"
                calculationInterval={AlertCalculationInterval.HOURLY}
            />
        </div>
    )
}

const HISTORY_POINTS: AlertEvaluationHistoryPoint[] = [
    { label: '11:00', value: 42 },
    { label: '11:15', value: 48 },
    { label: '11:30', value: 71, firedAtTime: true },
    { label: '11:45', value: 64, firedAtTime: true },
    { label: '12:00', value: 53, firedAtTime: false },
    { label: '12:15', value: 38, firedAtTime: false },
    { label: '12:30', value: 76, firedAtTime: true },
]

const HISTORY_THRESHOLDS: AlertEvaluationThreshold[] = [{ direction: 'upper', value: 60, label: 'Alert above 60' }]

function EvaluationHistoryStory(): JSX.Element {
    return (
        <div className="max-w-3xl border rounded bg-surface-primary p-4">
            <AlertEvaluationHistoryChart
                points={HISTORY_POINTS}
                valueLabel="Events"
                thresholds={HISTORY_THRESHOLDS}
                historyLimit={20}
                evaluationsTotal={47}
                evaluationNoun="evaluation"
                tableAvailable
            />
        </div>
    )
}

const meta: Meta = {
    title: 'Products/Alerts/Shared components',
    parameters: {
        layout: 'fullscreen',
    },
    decorators: [
        (Story): JSX.Element => (
            <div className="min-h-screen bg-bg-primary p-4">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof meta>

export const Editor: Story = { render: () => <EditorStory /> }
export const EditorLoading: Story = {
    render: () => <EditorLoadingStory />,
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Definition: Story = { render: () => <DefinitionStory /> }
export const AdvancedOptions: Story = { render: () => <AdvancedOptionsStory /> }
export const Notifications: Story = { render: () => <NotificationsStory /> }
export const NotificationsMultipleSlackWorkspaces: Story = { render: () => <MultipleSlackWorkspacesStory /> }
export const QuietHours: Story = { render: () => <QuietHoursStory /> }
export const EvaluationHistory: Story = { render: () => <EvaluationHistoryStory /> }
