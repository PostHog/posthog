import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import type { UserCustomerAnalyticsConfigApi } from '../../generated/api.schemas'
import { CustomerAnalyticsNotifications } from './CustomerAnalyticsNotifications'
import { CustomerAnalyticsTaskDigest } from './CustomerAnalyticsTaskDigest'
import { TaskDigestModal } from './TaskDigestModal'

const CONFIG_URL = '/api/projects/:team_id/user_customer_analytics_config/@me/'

const disabledConfig: UserCustomerAnalyticsConfigApi = {
    pinned_properties: [],
    task_digest: { enabled: false, send_time: '09:00', cadence: 'weekdays' },
}

const enabledConfig: UserCustomerAnalyticsConfigApi = {
    pinned_properties: [],
    task_digest: { enabled: true, send_time: '07:00', cadence: 'every_day' },
}

interface TaskDigestStoryProps {
    config?: UserCustomerAnalyticsConfigApi
    loading?: boolean
    failing?: boolean
    notifications?: boolean
    modal?: boolean
    saving?: boolean
    saveFails?: boolean
    width?: 'normal' | 'narrow'
}

function TaskDigestStory({
    config = disabledConfig,
    loading,
    failing,
    width,
    notifications,
    modal,
    saving,
    saveFails,
}: TaskDigestStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/event_streams/': [],
            [CONFIG_URL]: () => {
                if (loading) {
                    return new Promise<never>(() => {})
                }
                if (failing) {
                    return [500, { detail: 'Could not load the preferences.' }]
                }
                return config
            },
        },
        patch: {
            [CONFIG_URL]: async ({ request }) => {
                if (saving) {
                    return new Promise<never>(() => {})
                }
                if (saveFails) {
                    return [500, { detail: 'Could not save the preferences.' }]
                }
                const body = (await request.json()) as Partial<UserCustomerAnalyticsConfigApi>
                return { ...config, ...body }
            },
        },
    })

    return (
        <div className={width === 'narrow' ? 'w-[520px] p-4' : 'w-[900px] p-4'}>
            {modal ? (
                <TaskDigestModal onClose={() => {}} />
            ) : notifications ? (
                <CustomerAnalyticsNotifications />
            ) : (
                <CustomerAnalyticsTaskDigest />
            )}
        </div>
    )
}

const meta: Meta<typeof TaskDigestStory> = {
    title: 'Customer analytics/Task digest',
    component: TaskDigestStory,
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS],
    },
}
export default meta

type Story = StoryObj<typeof TaskDigestStory>

export const Disabled: Story = {}

export const Enabled: Story = { args: { config: enabledConfig } }

export const Loading: Story = {
    args: { loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const LoadFailed: Story = { args: { failing: true } }

export const DisabledNarrow: Story = { args: { width: 'narrow' } }

export const EnabledNarrow: Story = { args: { config: enabledConfig, width: 'narrow' } }

export const Notifications: Story = {
    args: { notifications: true },
    parameters: {
        featureFlags: [
            FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
        ],
    },
}
export const NotificationsNarrow: Story = { ...Notifications, args: { notifications: true, width: 'narrow' } }
export const Saving: Story = { args: { saving: true } }
export const SaveFailed: Story = { args: { saveFails: true } }

export const TasksModal: Story = {
    args: { modal: true },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonModal', waitForSelector: '.LemonModal' } },
}
