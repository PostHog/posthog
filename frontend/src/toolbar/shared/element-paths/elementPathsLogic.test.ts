import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { elementsLogic } from '~/toolbar/shared/elements/elementsLogic'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'

import type { ElementPathsResult } from './elementPathsApiTypes'
import { elementPathsLogic } from './elementPathsLogic'

jest.mock('~/toolbar/shared/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const PATH_RESULT: ElementPathsResult = {
    date_from: '2026-11-21T00:00:00Z',
    date_to: '2026-11-28T00:00:00Z',
    anchor_click_count: 40,
    anchor_session_count: 30,
    analyzed_session_count: 30,
    paths: [
        {
            session_count: 12,
            share_of_anchor_sessions: 0.4,
            anchor_index: 1,
            nodes: [
                {
                    label: '/pricing',
                    is_anchor: false,
                    step_is_exact: true,
                    step: { type: 'pageview', url: '/pricing', url_matching: 'contains' },
                },
                {
                    label: 'Sign up',
                    is_anchor: true,
                    step_is_exact: true,
                    step: { type: 'element_click', selector: '[data-attr="signup"]', url_matching: 'exact' },
                },
            ],
        },
    ],
}

type FetchReply = { status: number; body: unknown }

describe('elementPathsLogic', () => {
    const savedFetch = global.fetch
    let pathRequests: { url: URL; reply: (reply: FetchReply) => void }[]

    beforeEach(() => {
        pathRequests = []
        global.fetch = jest.fn((input: RequestInfo | URL) => {
            const url = new URL(String(input))
            if (!url.pathname.endsWith('/user_journeys/element_paths/')) {
                return Promise.resolve(new Response(JSON.stringify({ results: [] }), { status: 200 }))
            }
            return new Promise<Response>((resolve) => {
                pathRequests.push({
                    url,
                    reply: ({ status, body }) => resolve(new Response(JSON.stringify(body), { status })),
                })
            })
        }) as typeof fetch
        // jsdom lays nothing out, and inspect mode only offers elements with a visible size.
        jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 100, 20))
        document.body.innerHTML = `
            <button data-attr="signup">Sign up</button>
            <button data-attr="pricing">See pricing</button>
        `
        initKeaTests()
        toolbarConfigLogic
            .build({ apiURL: 'http://localhost', accessToken: 'test-token', teamId: 2, projectId: 1 })
            .mount()
        elementsLogic.mount()
        elementsLogic.actions.enableInspect()
    })

    afterEach(() => {
        global.fetch = savedFetch
        jest.restoreAllMocks()
    })

    function button(dataAttr: string): HTMLElement {
        return document.querySelector(`[data-attr="${dataAttr}"]`) as HTMLElement
    }

    it('loads nothing until an element is selected, and asks about the selected element on this page', async () => {
        window.history.replaceState({}, '', '/pricing')
        const logic = elementPathsLogic()
        logic.mount()
        elementsLogic.actions.setHoverElement(button('signup'))
        expect(logic.values.elementPathsView).toEqual({ status: 'idle' })
        expect(pathRequests).toHaveLength(0)

        elementsLogic.actions.setSelectedElement(button('signup'))
        expect(logic.values.elementPathsView).toEqual({ status: 'loading' })
        expect(pathRequests).toHaveLength(1)
        const params = Object.fromEntries(pathRequests[0].url.searchParams)
        // kea-router pads a value that parses as JSON with a space, and the endpoint trims it.
        expect(params.selector.trim()).toEqual('[data-attr="signup"]')
        expect(params).toMatchObject({
            text: 'Sign up',
            url_matching: 'regex',
            date_from: '-7d',
        })
        expect(new RegExp(params.url).test('http://localhost/pricing/?utm_source=ads#plans')).toBe(true)
        expect(new RegExp(params.url).test('http://localhost/pricing-old')).toBe(false)
    })

    it.each<[string, FetchReply, string]>([
        ['the project has no user journeys', { status: 404, body: { detail: 'Not found.' } }, 'unavailable'],
        ['the query fails', { status: 500, body: { detail: 'Server error' } }, 'error'],
        [
            'nobody clicked the element',
            { status: 200, body: { ...PATH_RESULT, anchor_click_count: 0, paths: [] } },
            'no-clicks',
        ],
        ['no path is shared', { status: 200, body: { ...PATH_RESULT, paths: [] } }, 'no-shared-path'],
        ['paths come back', { status: 200, body: PATH_RESULT }, 'paths'],
    ])('shows the right state when %s', async (_, reply, status) => {
        const logic = elementPathsLogic()
        logic.mount()
        await expectLogic(logic, () => {
            elementsLogic.actions.setSelectedElement(button('signup'))
            pathRequests[0].reply(reply)
        }).toDispatchActions(['loadElementPathsSuccess'])
        expect(logic.values.elementPathsView.status).toEqual(status)
    })

    it('asks again on retry, and shows loading until the new answer arrives', async () => {
        const logic = elementPathsLogic()
        logic.mount()
        await expectLogic(logic, () => {
            elementsLogic.actions.setSelectedElement(button('signup'))
            pathRequests[0].reply({ status: 500, body: { detail: 'Server error' } })
        }).toDispatchActions(['loadElementPathsSuccess'])

        logic.actions.retryElementPaths()
        expect(pathRequests).toHaveLength(2)
        expect(logic.values.elementPathsView).toEqual({ status: 'loading' })

        await expectLogic(logic, () => {
            pathRequests[1].reply({ status: 200, body: PATH_RESULT })
        }).toDispatchActions(['loadElementPathsSuccess'])
        expect(logic.values.elementPathsView.status).toEqual('paths')
    })

    it('ignores the answer for an element that is no longer selected', async () => {
        const logic = elementPathsLogic()
        logic.mount()
        elementsLogic.actions.setSelectedElement(button('signup'))
        elementsLogic.actions.setSelectedElement(button('pricing'))
        expect(pathRequests.map(({ url }) => url.searchParams.get('text'))).toEqual(['Sign up', 'See pricing'])

        await expectLogic(logic, () => {
            pathRequests[1].reply({ status: 200, body: { ...PATH_RESULT, paths: [] } })
            pathRequests[0].reply({ status: 200, body: PATH_RESULT })
        }).toFinishAllListeners()
        expect(logic.values.elementPathsView.status).toEqual('no-shared-path')

        elementsLogic.actions.setSelectedElement(null)
        expect(logic.values.elementPathsView).toEqual({ status: 'idle' })
    })
})
