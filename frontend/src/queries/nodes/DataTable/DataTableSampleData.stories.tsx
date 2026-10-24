import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { SAMPLE_EVENTS_SOURCE } from 'scenes/activity/explore/sampleEventRows'

import { mswDecorator } from '~/mocks/browser'
import { defaultDataTableColumns, getDefaultDataTablePersonColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { SAMPLE_PERSONS_SOURCE } from 'products/persons/frontend/samplePersonRows'

const TEAM_WITHOUT_EVENTS = { ...MOCK_DEFAULT_TEAM, ingested_event: false }

function eventsTable(select: string[]): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.EventsQuery, select, after: '-24h' },
    }
}

function WideAndNarrow({ query }: { query: DataTableNode }): JSX.Element {
    const context: QueryContext = {
        dataTableSampleRows: query.source.kind === NodeKind.ActorsQuery ? SAMPLE_PERSONS_SOURCE : SAMPLE_EVENTS_SOURCE,
    }
    return (
        <div className="flex flex-col gap-6">
            <div className="w-240">
                <Query query={query} context={context} />
            </div>
            {/* The width of a scene with the side panel open in a 1280px window */}
            <div className="w-130">
                <Query query={query} context={context} />
            </div>
        </div>
    )
}

type Story = StoryObj<{ query: DataTableNode }>
const meta: Meta<{ query: DataTableNode }> = {
    title: 'Queries/DataTable/Sample data',
    parameters: {
        layout: 'padded',
        mockDate: '2026-10-23T12:00:00Z',
        testOptions: {
            waitForSelector: '[data-attr$="-table-sample-data"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': { count: 0, results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': { results: [], hasMore: false },
            },
        }),
    ],
    // teamLogic reads the team from the app context, not the API. `beforeEach` runs before Kea mounts it.
    beforeEach: () => {
        const appContext = window.POSTHOG_APP_CONTEXT
        const originalTeam = appContext?.current_team
        if (appContext) {
            appContext.current_team = TEAM_WITHOUT_EVENTS
        }
        return () => {
            if (appContext) {
                appContext.current_team = originalTeam ?? null
            }
        }
    },
    render: ({ query }) => <WideAndNarrow query={query} />,
}
export default meta

export const DefaultColumns: Story = {
    args: { query: eventsTable(defaultDataTableColumns(NodeKind.EventsQuery)) },
}

export const WithCustomColumn: Story = {
    args: {
        query: eventsTable([...defaultDataTableColumns(NodeKind.EventsQuery), 'properties.$browser_version']),
    },
}

export const Persons: Story = {
    args: {
        query: {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.ActorsQuery,
                select: [
                    ...getDefaultDataTablePersonColumns(true),
                    'properties.$initial_utm_campaign',
                    'person.$delete',
                ],
            },
            full: true,
            showCount: true,
        },
    },
}
