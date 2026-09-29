import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TOP_REPORT_COUNT, reportIdFromPath, todayLogic } from './todayLogic'
import { GENERAL_REPORT_PROMPTS, briefingForReports, reportPrompts } from './todaySignalReports'

describe('todayLogic', () => {
    let listResponse: [number, any]
    let listParams: URLSearchParams | null

    beforeEach(() => {
        listResponse = [200, { results: [], count: 0 }]
        listParams = null
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    listParams = new URL(request.url).searchParams
                    return listResponse
                },
            },
        })
        initKeaTests()
    })

    it('asks for the top actionable reports by priority and counts the rest', async () => {
        const reports = [makeReport({ id: 'a' }), makeReport({ id: 'b' })]
        listResponse = [200, { results: reports, count: 9 }]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ reports, moreReportCount: 7 })
        expect(Object.fromEntries(listParams!.entries())).toMatchObject({
            status: 'ready,pending_input',
            actionability: 'immediately_actionable,requires_human_input',
            ordering: 'priority,-updated_at',
            limit: String(TOP_REPORT_COUNT),
        })
    })

    it('keeps a failed load apart from an empty list', async () => {
        listResponse = [500, { detail: 'Server error' }]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ topReports: null, reportsFailed: true })
    })

    test.each([
        ['/project/1/home/reports/abc', 'abc'],
        ['/home/reports/abc/', 'abc'],
        ['/project/1/home', null],
        ['/project/1/home/reports/abc/signals', null],
        ['/project/1/inbox/reports/abc', null],
    ])('reads the report id from %s', (pathname, reportId) => {
        expect(reportIdFromPath(pathname)).toBe(reportId)
    })

    it('links every report from the briefing and keeps acronyms in titles', () => {
        const briefing = briefingForReports([
            makeReport({
                id: 'a',
                title: 'Signup form rejects emails',
                implementation_pr_url: 'https://example.com/1',
            }),
            makeReport({ id: 'b', title: 'Pricing page drops off' }),
            makeReport({ id: 'c', title: 'LLM costs doubled' }),
        ])

        expect(briefing.flat().filter((segment) => segment.reportId)).toEqual([
            { text: 'Signup form rejects emails', reportId: 'a', highlight: true },
            { text: 'pricing page drops off', reportId: 'b' },
            { text: 'LLM costs doubled', reportId: 'c' },
        ])
    })

    test.each([
        ['an action-capable report', {}, ['Draft the fix']],
        ['a report with a pull request', { implementation_pr_url: 'https://example.com/1' }, GENERAL_REPORT_PROMPTS],
        ['a report judged not actionable', { actionability: 'not_actionable' }, GENERAL_REPORT_PROMPTS],
    ])('offers the right prompts for %s', (_, overrides, expected) => {
        const report = makeReport({ suggested_prompts: ['Draft the fix'], ...(overrides as Partial<SignalReport>) })
        expect(reportPrompts(report)).toEqual(expected)
    })
})
