import { RenderResult, cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PersonListApi } from '../../generated/api.schemas'
import { makeSessionListPage } from '../sessions/testFixtures'
import { makeTraceListPage } from '../traces/testFixtures'
import { PeopleListHost } from './PeopleListHost'
import { peopleListLogic } from './peopleListLogic'
import {
    PEOPLE_FIRST_SEEN_URL,
    PEOPLE_NEW_COUNT_URL,
    PEOPLE_URL,
    makeFirstSeenAnswer,
    makePersonListItem,
    makePersonListPage,
} from './testFixtures'

const PAGE = makePersonListPage([], {
    count: 2,
    counts: { anonymous: 1 },
    results: [
        makePersonListItem({
            id: 'person-a',
            person: { distinctId: 'ana@example.com', label: 'Ana Example' },
        }),
        makePersonListItem({
            id: 'person-b',
            person: { distinctId: 'bob@example.com', label: 'Anonymous bob@exam' },
            anonymous: true,
        }),
    ],
})

function attr(view: RenderResult, name: string): HTMLElement {
    const element = view.container.querySelector<HTMLElement>(`[data-attr="${name}"]`)
    if (!element) {
        throw new Error(`expected ${name} to render`)
    }
    return element
}

describe('PeopleListHost', () => {
    let answer: PersonListApi

    beforeEach(() => {
        answer = PAGE
        useMocks({
            get: {
                [PEOPLE_URL]: () => [200, answer],
                [PEOPLE_NEW_COUNT_URL]: () => [200, { count: 1 }],
                // An opened row mounts the person's drawer, which reads their recent traces and sessions.
                '/api/projects/:team_id/ai_observability/traces/': () => [200, makeTraceListPage([])],
                '/api/projects/:team_id/ai_observability/sessions/': () => [200, makeSessionListPage([])],
            },
            post: {
                [PEOPLE_FIRST_SEEN_URL]: async ({ request }: { request: Request }) => [
                    200,
                    makeFirstSeenAnswer((await request.json()).person_ids, ['person-a']),
                ],
            },
        })
        initKeaTests()
        localStorage.clear()
    })

    afterEach(() => {
        cleanup()
    })

    function renderHost(url = urls.aiObservabilityUsers()): RenderResult {
        router.actions.push(url)
        return render(<PeopleListHost />)
    }

    it('tags the people their first seen read calls new, and shows the new count on its chip', async () => {
        const view = renderHost()

        await view.findByText('Ana Example')
        await waitFor(() =>
            expect(within(attr(view, 'ai-observability-people-list')).getAllByText('New')).toHaveLength(1)
        )
        await waitFor(() =>
            expect(attr(view, 'ai-observability-people-list-quick-filter-new').textContent).toBe('New1')
        )
    })

    it('opens a clicked row as the person in the url', async () => {
        const view = renderHost()
        const row = (await view.findByText('Anonymous bob@exam')).closest('tr')
        if (!row) {
            throw new Error('expected the person to render in a row')
        }

        fireEvent.click(row.querySelectorAll('td')[1])
        await expectLogic(peopleListLogic()).toFinishAllListeners()

        expect(router.values.searchParams).toMatchObject({ person: 'person-b' })
    })

    it('shows the setup card when every person in range is anonymous', async () => {
        answer = makePersonListPage([], { needsIdentification: true })

        const view = renderHost()

        await view.findByText('Link traces to people')
        expect(attr(view, 'ai-observability-people-setup-traces').getAttribute('href')).toContain(
            urls.aiObservabilityTraces()
        )
    })
})
