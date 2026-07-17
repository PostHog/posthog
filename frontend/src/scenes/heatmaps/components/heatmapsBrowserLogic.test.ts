import { expectLogic } from 'kea-test-utils'

import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { heatmapLogic } from 'scenes/heatmaps/scenes/heatmap/heatmapLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

describe('heatmapsBrowserLogic', () => {
    let browserLogic: ReturnType<typeof heatmapsBrowserLogic.build>
    let authLogic: ReturnType<typeof authorizedUrlListLogic.build>
    let logic: ReturnType<typeof heatmapLogic.build>

    beforeEach(() => {
        useMocks({
            post: { '/api/environments/:team_id/query/': () => [200, { results: [] }] },
            patch: {
                '/api/environments/:team_id': (req: any) => {
                    const body = JSON.parse(req.request?.body ?? '{}')
                    return [200, { app_urls: body.app_urls }]
                },
                '/api/projects/:team': [200, {}],
            },
        })
        initKeaTests()
        browserLogic = heatmapsBrowserLogic({ iframeRef: { current: null } as any })
        browserLogic.mount()
        authLogic = authorizedUrlListLogic({
            ...defaultAuthorizedUrlProperties,
            type: AuthorizedUrlListType.TOOLBAR_URLS,
        })
        authLogic.mount()
        logic = heatmapLogic({ id: 'new' })
        logic.mount()
    })

    // Guards the forbidden-URL banner + Save button on /heatmaps/new: both read isBrowserUrlAuthorized,
    // which must flip the moment a domain is authorized rather than waiting for the field to be re-touched.
    it('isBrowserUrlAuthorized reactively clears once the domain is authorized', async () => {
        browserLogic.actions.setDataUrl('https://not-authorized.example.org/page')
        await expectLogic(logic).toMatchValues({ isBrowserUrlAuthorized: false })

        authLogic.actions.addUrl('https://not-authorized.example.org')

        await expectLogic(logic).toMatchValues({ isBrowserUrlAuthorized: true })
    })
})
