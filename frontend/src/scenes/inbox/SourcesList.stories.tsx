import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { SourcesList } from './SourcesList'

const meta: Meta = {
    title: 'Scenes-App/Inbox/Sources List',
    component: SourcesList,
}
export default meta

type Story = StoryObj<{}>

const SOURCE_CONFIGS_MOCK = {
    count: 2,
    next: null,
    previous: null,
    results: [
        {
            id: 'cfg-zendesk',
            source_product: 'zendesk',
            source_type: 'ticket',
            enabled: true,
            config: {},
            created_at: '2026-05-01T10:00:00Z',
            updated_at: '2026-05-01T10:00:00Z',
            status: null,
        },
        {
            id: 'cfg-error-tracking-issue-created',
            source_product: 'error_tracking',
            source_type: 'issue_created',
            enabled: true,
            config: {},
            created_at: '2026-05-01T10:00:00Z',
            updated_at: '2026-05-01T10:00:00Z',
            status: null,
        },
    ],
}

/**
 * Default view of the Inbox sources panel without the `csp-reporting-signal-source`
 * feature flag. CSP violations row is hidden — what most teams see today.
 */
export const WithoutCspFlag: Story = {
    parameters: {
        // PRODUCT_AUTONOMY gates the `loadSourceConfigs` call in afterMount, so we
        // need it on for the mocked rows to populate.
        featureFlags: [FEATURE_FLAGS.PRODUCT_AUTONOMY],
    },
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': SOURCE_CONFIGS_MOCK,
            },
        })
        return <SourcesList />
    },
}

/**
 * Same view with the `csp-reporting-signal-source` flag enabled. Shows the new
 * "CSP violations" toggle row between GitHub Issues and the "coming soon" Slack tile.
 */
export const WithCspFlag: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.PRODUCT_AUTONOMY, FEATURE_FLAGS.CSP_REPORTING_SIGNAL_SOURCE],
    },
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': SOURCE_CONFIGS_MOCK,
            },
        })
        return <SourcesList />
    },
}

/**
 * Flag on AND the team already has CSP reporting enabled — toggle is checked.
 */
export const WithCspFlagAndEnabled: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.PRODUCT_AUTONOMY, FEATURE_FLAGS.CSP_REPORTING_SIGNAL_SOURCE],
    },
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': {
                    ...SOURCE_CONFIGS_MOCK,
                    count: SOURCE_CONFIGS_MOCK.count + 1,
                    results: [
                        ...SOURCE_CONFIGS_MOCK.results,
                        {
                            id: 'cfg-csp',
                            source_product: 'csp_reporting',
                            source_type: 'violation',
                            enabled: true,
                            config: {},
                            created_at: '2026-05-14T10:00:00Z',
                            updated_at: '2026-05-14T10:00:00Z',
                            status: null,
                        },
                    ],
                },
            },
        })
        return <SourcesList />
    },
}
