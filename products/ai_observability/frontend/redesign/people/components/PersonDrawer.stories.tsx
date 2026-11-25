import type { Meta, StoryObj } from '@storybook/react'

import type { SessionPreviewApi, TracePreviewApi } from '../../../generated/api.schemas'
import { makeSessionListItem, makeSessionPreview } from '../../sessions/testFixtures'
import type { CellLoads, TraceCellLoad } from '../../shared/cellLoads'
import { makeTraceListItem, makeTracePreview, ready } from '../../traces/testFixtures'
import { makePersonListItem } from '../testFixtures'
import { PersonDrawer } from './PersonDrawer'

const TRACES = [
    makeTraceListItem({ id: 'trace-1', name: 'answer-billing-question', createdAt: '2026-11-24T16:40:00Z' }),
    makeTraceListItem({ id: 'trace-2', name: 'summarize-invoice', createdAt: '2026-11-24T15:02:00Z' }),
    makeTraceListItem({ id: 'trace-3', name: null, createdAt: '2026-11-23T09:30:00Z' }),
]
const SESSIONS = [
    makeSessionListItem({ id: 'session-1', lastSeen: '2026-11-24T16:42:00Z' }),
    makeSessionListItem({ id: 'session-2', turnCount: 1, lastSeen: '2026-11-22T11:05:00Z' }),
]
const TRACE_TITLES: CellLoads<TracePreviewApi> = new Map<string, TraceCellLoad<TracePreviewApi>>([
    ['trace-1', ready(makeTracePreview('trace-1'))],
    ['trace-2', ready(makeTracePreview('trace-2', { input: 'Summarize my last invoice in two lines.' }))],
    ['trace-3', ready(makeTracePreview('trace-3', { input: null }))],
])
const SESSION_TITLES: CellLoads<SessionPreviewApi> = new Map<string, TraceCellLoad<SessionPreviewApi>>([
    ['session-1', ready(makeSessionPreview('session-1'))],
    ['session-2', ready(makeSessionPreview('session-2', { input: 'Can I change my billing email?' }))],
])

const meta: Meta<typeof PersonDrawer> = {
    title: 'Scenes-App/AI observability/People/Person drawer',
    component: PersonDrawer,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        person: makePersonListItem({
            id: 'person-1',
            person: { distinctId: 'ana@example.com', label: 'Ana Example' },
            sessionCount: 12,
            traceCount: 48,
            cost: 1.2875,
        }),
        status: 'ready',
        firstSeen: ready({ firstSeen: '2026-11-20T09:15:00Z', checkedFrom: '2026-10-18', isNew: true }),
        recentTraces: ready(TRACES),
        traceTitles: TRACE_TITLES,
        recentSessions: ready(SESSIONS),
        sessionTitles: SESSION_TITLES,
        sessionHref: (session) => `#${session.id}`,
        viewAllHref: '#traces',
        personHref: '#person',
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-96 p-4">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof PersonDrawer>

export const Loaded: Story = {}

export const LoadingSections: Story = {
    args: {
        firstSeen: { status: 'loading' },
        recentTraces: { status: 'loading' },
        recentSessions: { status: 'loading' },
    },
}

export const FailedSection: Story = {
    args: { recentTraces: { status: 'error' } },
}

export const NoSessions: Story = {
    args: { recentSessions: ready([]) },
}

export const AnonymousPerson: Story = {
    args: {
        person: makePersonListItem({
            id: 'person-2',
            person: {
                distinctId: '0192f3c9-a1d2-7b4e-9c8f-5e6d7a8b9c0d',
                label: 'Anonymous 0192f3c9',
            },
            anonymous: true,
            cost: null,
        }),
        personHref: null,
    },
}

export const NotFound: Story = {
    args: { person: null, status: 'not_found' },
}
