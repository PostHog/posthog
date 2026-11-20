import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { businessKnowledgeLogic } from '../../scenes/sources/businessKnowledgeLogic'
import { businessKnowledgeSetupCardLogic } from './businessKnowledgeSetupCardLogic'

describe('businessKnowledgeSetupCardLogic', () => {
    let logic: ReturnType<typeof businessKnowledgeSetupCardLogic.build>
    let pageviewHosts: [string, number][]
    let createdSources: Record<string, unknown>[]

    beforeEach(() => {
        pageviewHosts = []
        createdSources = []
        useMocks({
            get: {
                '/api/projects/:team_id/business_knowledge/sources/': { count: 0, results: [] },
                '/api/projects/:team_id/business_knowledge/libraries/': { count: 0, results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': () => [200, { results: pageviewHosts }],
                '/api/projects/:team_id/business_knowledge/sources/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    createdSources.push(body)
                    return [201, { id: 'source-1', name: body.name, chunk_count: 0 }]
                },
            },
        })
        initKeaTests()
        logic = businessKnowledgeSetupCardLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['fills an empty field with the most visited public host', '', 'https://hedgebox.net'],
        ['keeps what the person already typed', 'https://docs.hedgebox.net', 'https://docs.hedgebox.net'],
    ])('%s', async (_, typed, expected) => {
        pageviewHosts = [
            ['localhost:8010', 900],
            ['hedgebox.net', 400],
        ]
        logic.mount()
        businessKnowledgeLogic.actions.setUrlSourceValue('url', typed)
        await expectLogic(logic).toDispatchActions(['loadSuggestedWebsiteSuccess']).toFinishAllListeners()

        expect(businessKnowledgeLogic.values.urlSource.url).toBe(expected)
    })

    it('creates a crawled source named after the site from a bare domain', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSuggestedWebsiteSuccess'])
        businessKnowledgeLogic.actions.setUrlSourceValue('url', 'www.hedgebox.net')
        logic.actions.submitWebsite('needs-setup', false)
        await expectLogic(businessKnowledgeLogic).toDispatchActions(['submitUrlSourceSuccess'])

        expect(createdSources).toEqual([
            expect.objectContaining({
                url: 'https://www.hedgebox.net',
                name: 'hedgebox.net',
                crawl_mode: 'same_origin',
            }),
        ])
    })

    it.each([['url'], ['file'], ['text']] as const)('opens the create modal on the %s tab', async (source) => {
        logic.mount()
        logic.actions.pickSource(source, 'needs-setup', false)
        await expectLogic(logic).toFinishAllListeners()

        expect(businessKnowledgeLogic.values.isCreateModalOpen).toBe(true)
        expect(businessKnowledgeLogic.values.createTab).toBe(source)
    })

    it.each([
        ['github', 'business-knowledge-github-repos'],
        ['support', 'business-knowledge-learn-from-support'],
    ] as const)('opens the %s setting in business knowledge settings', async (source, settingId) => {
        logic.mount()
        logic.actions.pickSource(source, 'needs-setup', false)
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toContain('/business-knowledge/settings')
        expect(router.values.hashParams).toEqual({ selectedSetting: settingId })
        expect(businessKnowledgeLogic.values.isCreateModalOpen).toBe(false)
    })
})
