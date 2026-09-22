import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { ModelsOverviewTab } from 'scenes/models/tabs/ModelsOverviewTab'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

const nodes = ['attention', 'behind'].flatMap((group) =>
    Array.from({ length: 12 }, (_, index) => ({
        id: `${group}-${index + 1}`,
        name: `${group}_model_${index + 1}`,
        type: 'matview',
        dag: 'example-dag',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        last_run_at: '2026-09-14T00:00:00Z',
        last_run_status: group === 'attention' ? 'Failed' : 'Completed',
        last_run_error: group === 'attention' ? 'Example refresh failed.' : null,
        sync_interval: '1hour',
        upstream_count: 0,
        downstream_count: 0,
    }))
)
const checks = Array.from({ length: 12 }, (_, index) => ({
    id: `check-${index + 1}`,
    name: `Example check ${index + 1}`,
    check_type: 'not_null',
    subject_type: 'view',
    subject_name: `example_view_${index + 1}`,
    subject_node_id: `attention-${index + 1}`,
    last_status: 'failed',
}))

const healthyNodes = Array.from({ length: 3 }, (_, index) => ({
    id: `healthy-${index + 1}`,
    name: `healthy_model_${index + 1}`,
    type: 'matview',
    dag: 'example-dag',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_run_at: '2026-09-15T00:00:00Z',
    last_run_status: 'Completed',
    last_run_error: null,
    sync_interval: '24hour',
    upstream_count: 0,
    downstream_count: 0,
}))
const passingChecks = [
    {
        id: 'check-1',
        name: 'Example check',
        check_type: 'not_null',
        subject_type: 'view',
        subject_name: 'example_view',
        subject_node_id: 'healthy-1',
        last_status: 'passed',
    },
]
const neverRunChecks = passingChecks.map((check) => ({ ...check, last_status: '' }))

function healthyMocks(checkRows: Record<string, any>[]): { mocks: Mocks } {
    return {
        mocks: {
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': {
                    results: healthyNodes,
                    count: healthyNodes.length,
                },
                '/api/projects/:team_id/data_quality_checks/': { results: checkRows, count: checkRows.length },
            },
        },
    }
}

const inMainContent =
    (widthClass: string): Decorator =>
    (Story) => (
        <div className={`@container/main-content ${widthClass}`}>
            <Story />
        </div>
    )

const meta: Meta<typeof ModelsOverviewTab> = {
    title: 'Products/Data modeling/Models overview',
    component: ModelsOverviewTab,
    beforeEach: () => {
        const context = window.POSTHOG_APP_CONTEXT!
        const previous = context.resource_access_control
        context.resource_access_control = {
            ...previous,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
        }
        return () => {
            context.resource_access_control = previous
        }
    },
    decorators: [mswDecorator({})],
    parameters: {
        featureFlags: [FEATURE_FLAGS.DATA_QUALITY_CHECKS],
        pageUrl: urls.models(),
        mockDate: '2026-09-15',
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/data_modeling_nodes/': { results: nodes, count: nodes.length },
                    '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
                    '/api/environments/:team_id/warehouse_saved_queries/': { results: [], count: 0 },
                    '/api/projects/:team_id/data_quality_checks/': { results: checks, count: checks.length },
                    '/api/projects/:team_id/data_quality_checks/health/': [],
                },
            },
        },
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof ModelsOverviewTab>
export const Paginated: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-128 max-w-full">
                <Story />
            </div>
        ),
    ],
}

export const PartialLastPage: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findAllByText('1-10 of 12 entries')
        await waitFor(() => {
            if (canvas.queryAllByText('1-10 of 12 entries').length !== 3) {
                throw new Error('All three overview tables must finish loading')
            }
        })
        const tables = ['attention', 'behind', 'failing-checks'].map((section) => {
            const table = canvasElement.querySelector<HTMLElement>(`[data-attr="models-overview-${section}"]`)!
            return { table, height: table.offsetHeight, top: table.getBoundingClientRect().top + window.scrollY }
        })
        for (const { table } of tables) {
            within(table).getByRole('button', { name: 'Previous page' })
            const next = within(table).getByRole('button', { name: 'Next page' })
            fireEvent.click(next)
            await within(table).findByText('11-12 of 12 entries')
            for (const initial of tables) {
                if (
                    initial.table.offsetHeight !== initial.height ||
                    initial.table.getBoundingClientRect().top + window.scrollY !== initial.top
                ) {
                    throw new Error('Paging must preserve table heights and the positions of surrounding sections')
                }
            }
        }
    },
}
export const NarrowPartialLastPage: Story = {
    ...Narrow,
    play: PartialLastPage.play,
}

export const Healthy: Story = {
    decorators: [inMainContent('w-256')],
    parameters: { msw: healthyMocks(passingChecks) },
}

export const HealthyWithoutChecks: Story = {
    decorators: [inMainContent('w-256')],
    parameters: { msw: healthyMocks([]) },
}

export const HealthyWithChecksNotRun: Story = {
    decorators: [inMainContent('w-256')],
    parameters: { msw: healthyMocks(neverRunChecks) },
}

export const HealthyWithDataQualityDisabled: Story = {
    decorators: [inMainContent('w-256')],
    parameters: { featureFlags: [], msw: healthyMocks(passingChecks) },
}

export const HealthyNarrow: Story = {
    decorators: [inMainContent('w-128')],
    parameters: { msw: healthyMocks(passingChecks) },
}

export const FirstView: Story = {
    decorators: [inMainContent('w-256')],
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/data_modeling_nodes/': { results: [], count: 0 },
                    '/api/projects/:team_id/data_quality_checks/': { results: [], count: 0 },
                },
            },
        },
    },
}
