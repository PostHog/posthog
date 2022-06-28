import { appEditorUrl, authorizedUrlsLogic } from 'scenes/toolbar-launch/authorizedUrlsLogic'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { urls } from 'scenes/urls'

describe('the authorized urls logic', () => {
    let logic: ReturnType<typeof authorizedUrlsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/trend/': (req) => {
                    if (JSON.parse(req.url.searchParams.get('events') || '[]')?.[0]?.throw) {
                        return [500, { status: 0, detail: 'error from the API' }]
                    }
                    return [200, { result: ['result from api'] }]
                },
            },
        })
        initKeaTests()
        logic = authorizedUrlsLogic()
        logic.mount()
    })

    it('encodes an app url correctly', () => {
        expect(appEditorUrl('http://127.0.0.1:8000')).toEqual(
            '/api/user/redirect_to_site/?userIntent=add-action&appUrl=http%3A%2F%2F127.0.0.1%3A8000'
        )
    })

    it('can be launched with adding a new URL focussed', async () => {
        router.actions.push(`${urls.toolbarLaunch()}?addNew=true`)
        await expectLogic(logic).toDispatchActions(['newUrl'])
    })

    it('can be launchd without focussing adding new URL', async () => {
        router.actions.push(urls.toolbarLaunch())
        await expectLogic(logic).toNotHaveDispatchedActions(['newUrl'])
    })

    describe('the proposed URL form', () => {
        it('shows errors when the value is invalid', async () => {
            await expectLogic(logic, () => {
                logic.actions.setProposedUrlValue('url', 'not a domain or url')
            }).toMatchValues({
                proposedUrl: { url: 'not a domain or url' },
                proposedUrlChanged: true,
                proposedUrlHasErrors: true,
                proposedUrlValidationErrors: { url: 'Please type a valid URL or domain.' },
            })
        })
    })
})
