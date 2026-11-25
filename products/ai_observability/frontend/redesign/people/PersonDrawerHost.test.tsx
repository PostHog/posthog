import { RenderResult, act, cleanup, fireEvent, render } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TracePageRequestApi } from '../../generated/api.schemas'
import { makeSessionListPage } from '../sessions/testFixtures'
import { TRACE_CELL_URLS, makeTraceListPage, makeTracePreview } from '../traces/testFixtures'
import { PersonDrawerHost } from './PersonDrawerHost'
import { personDrawerLogic } from './personDrawerLogic'
import { PEOPLE_URL, makePersonListItem, makePersonListPage } from './testFixtures'

// The trace drawer has its own tests. Here it only has to show which way leads back.
jest.mock('../trace/TraceDrawerHost', () => {
    const { createElement } = jest.requireActual('react')
    return {
        TraceDrawerHost: ({ back }: { back: { label: string; onBack: () => void } }) =>
            createElement('button', { 'data-attr': 'trace-drawer-back', onClick: back.onBack }, back.label),
    }
})

const PERSON_ID = 'person-ana'
const PAGE = makePersonListPage([], {
    results: [makePersonListItem({ id: PERSON_ID, person: { distinctId: 'ana@example.com', label: 'Ana Example' } })],
})

function attrs(view: RenderResult, name: string): HTMLElement[] {
    return [...view.container.querySelectorAll<HTMLElement>(`[data-attr="${name}"]`)]
}

describe('PersonDrawerHost', () => {
    beforeEach(() => {
        useMocks({
            get: {
                [PEOPLE_URL]: () => [200, PAGE],
                '/api/projects/:team_id/ai_observability/traces/': () => [
                    200,
                    makeTraceListPage(['trace-a', 'trace-b']),
                ],
                '/api/projects/:team_id/ai_observability/sessions/': () => [200, makeSessionListPage([])],
            },
            post: {
                [TRACE_CELL_URLS.previews]: async ({ request }: { request: Request }) => {
                    const { trace_ids }: TracePageRequestApi = await request.json()
                    return [200, { items: trace_ids.map((id) => makeTracePreview(id)) }]
                },
            },
        })
        initKeaTests()
        localStorage.clear()
        panelLayoutLogic.mount()
        panelLayoutLogic.actions.setMainContentRect(document.body.getBoundingClientRect())
    })

    afterEach(() => {
        cleanup()
    })

    it('swaps the person for a recent trace, and goes back to the person from it', async () => {
        router.actions.push(combineUrl(urls.aiObservabilityUsers(), { person: PERSON_ID }).url)
        const view = render(<PersonDrawerHost personId={PERSON_ID} />)
        await act(() => expectLogic(personDrawerLogic({ personId: PERSON_ID })).toFinishAllListeners())

        expect(view.queryByText('Recent sessions')).toBeNull()
        fireEvent.click(attrs(view, 'ai-observability-person-drawer-trace')[1])

        expect(router.values.searchParams).toMatchObject({ person: PERSON_ID, trace: 'trace-b' })
        expect(attrs(view, 'ai-observability-person-drawer')).toEqual([])
        const back = attrs(view, 'trace-drawer-back')[0]
        expect(back.textContent).toEqual('Ana Example')

        fireEvent.click(back)

        expect(router.values.searchParams).toMatchObject({ person: PERSON_ID })
        expect(router.values.searchParams.trace).toBeUndefined()
        expect(attrs(view, 'ai-observability-person-drawer')).toHaveLength(1)
    })
})
