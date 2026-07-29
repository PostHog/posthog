import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import { initKeaTests } from '~/test/init'

import { heatmapsBrowserLogic, normalizeHeatmapDataUrl } from './heatmapsBrowserLogic'

describe('heatmapsBrowserLogic', () => {
    describe('normalizeHeatmapDataUrl', () => {
        it.each([
            ['example.com', null],
            ['   ', null],
            ['', null],
            [null, null],
            ['h', null],
            ['https://', null],
            ['https://example.com', { href: 'https://example.com/', matchType: 'exact' }],
            ['https://example.com/pricing', { href: 'https://example.com/pricing', matchType: 'exact' }],
            ['  https://example.com/pricing  ', { href: 'https://example.com/pricing', matchType: 'exact' }],
            ['https://example.com/users/*', { href: 'https://example.com/users/*', matchType: 'pattern' }],
        ] as const)('normalizeHeatmapDataUrl(%s) → %s', (input, expected) => {
            expect(normalizeHeatmapDataUrl(input)).toEqual(expected)
        })
    })

    describe('page URL query-param sync', () => {
        beforeEach(() => {
            initKeaTests()
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
            router.actions.push('/heatmaps/new')
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('keeps the page URL cleared on the first delete instead of resurrecting it from the querystring', async () => {
            const logic = heatmapsBrowserLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setDisplayUrl('https://example.com/pricing')
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.searchParams.pageURL).toBe('https://example.com/pricing')

            logic.actions.setDisplayUrl('')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.displayUrl).toBe('')
            expect(router.values.searchParams.pageURL).toBeUndefined()
        })
    })

    describe('display URL authorization', () => {
        beforeEach(() => {
            initKeaTests()
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
            router.actions.push('/heatmaps/new')
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it.each([
            ['https://example.com/pricing', 'https://example.com/*', true],
            // The data URL can be authorized while the page we embed and launch the toolbar
            // against is on an entirely different, unauthorized host.
            ['https://unauthorized.com/pricing', 'https://example.com/*', false],
            [null, 'https://example.com/*', false],
        ] as const)('display URL %s with data URL %s is authorized: %s', (displayUrl, dataUrl, expected) => {
            const authorizedUrls = authorizedUrlListLogic({
                ...defaultAuthorizedUrlProperties,
                type: AuthorizedUrlListType.TOOLBAR_URLS,
            })
            authorizedUrls.mount()
            authorizedUrls.actions.setAuthorizedUrls(['https://example.com'])

            const logic = heatmapsBrowserLogic()
            logic.mount()
            logic.actions.setDisplayUrl(displayUrl)
            logic.actions.setDataUrl(dataUrl)

            expect(logic.values.isBrowserUrlAuthorized).toBe(true)
            expect(logic.values.isDisplayUrlAuthorized).toBe(expected)
        })
    })
})
