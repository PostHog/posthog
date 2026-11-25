import type { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { PeopleFirstSeenRequestApi } from '../../generated/api.schemas'
import { PeopleListHost } from './PeopleListHost'
import {
    PEOPLE_FIRST_SEEN_URL,
    PEOPLE_NEW_COUNT_URL,
    PEOPLE_URL,
    makeFirstSeenAnswer,
    makePersonListItem,
    makePersonListPage,
} from './testFixtures'

const PAGE = makePersonListPage([], {
    count: 132,
    counts: { anonymous: 12 },
    results: [
        makePersonListItem({
            id: 'person-1',
            person: { distinctId: 'ana@example.com', label: 'Ana Example' },
            traceCount: 412,
            sessionCount: 31,
            cost: 8.21,
        }),
        makePersonListItem({
            id: 'person-2',
            person: { distinctId: 'sam@example.com', label: 'Sam Example' },
            sessionCount: 0,
            cost: null,
        }),
        makePersonListItem({
            id: 'person-3',
            person: {
                distinctId: '0192f3c9-a1d2-7b4e-9c8f-5e6d7a8b9c0d',
                label: 'Anonymous 0192f3c9',
            },
            anonymous: true,
        }),
    ],
})

const FIRST_SEEN_MOCK = {
    [PEOPLE_FIRST_SEEN_URL]: async ({ request }: { request: Request }) => {
        const body: PeopleFirstSeenRequestApi = await request.json()
        return [200, makeFirstSeenAnswer(body.person_ids, ['person-1'])]
    },
}

const meta: Meta<typeof PeopleListHost> = {
    title: 'Scenes-App/AI observability/People/People list',
    component: PeopleListHost,
    decorators: [
        mswDecorator({}),
        (StoryComponent) => (
            <div className="w-120">
                <StoryComponent />
            </div>
        ),
    ],
    parameters: {
        msw: { mocks: { get: { [PEOPLE_URL]: PAGE, [PEOPLE_NEW_COUNT_URL]: { count: 7 } }, post: FIRST_SEEN_MOCK } },
        mockDate: '2026-11-25',
        pageUrl: urls.aiObservabilityUsers(),
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=Ana Example' },
    },
}
export default meta

type Story = StoryObj<typeof PeopleListHost>

export const Rows: Story = {}

export const Loading: Story = {
    parameters: {
        msw: { mocks: { get: { [PEOPLE_URL]: () => new Promise(() => {}) } } },
        testOptions: { snapshotBrowsers: [], waitForSelector: '.LemonTableLoader' },
    },
}

export const NoPeopleMatch: Story = {
    parameters: {
        msw: { mocks: { get: { [PEOPLE_URL]: makePersonListPage([]) } } },
        pageUrl: `${urls.aiObservabilityUsers()}?view=new`,
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=No people match' },
    },
}

export const SetupCard: Story = {
    parameters: {
        msw: { mocks: { get: { [PEOPLE_URL]: makePersonListPage([], { needsIdentification: true }) } } },
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=Link traces to people' },
    },
}

export const Failed: Story = {
    parameters: {
        msw: { mocks: { get: { [PEOPLE_URL]: () => [500, { detail: 'Read failed' }] } } },
        testOptions: { snapshotBrowsers: [], waitForSelector: "text=Couldn't load people" },
    },
}
