import { kea, path } from 'kea'
import { router } from 'kea-router'
import { expectLogic, partial, truth } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import type { AppContext } from '~/types'

import { sceneLogic } from './sceneLogic'
import type { testLogicType } from './sceneLogic.testType'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        get: jest.fn(),
        update: jest.fn(),
    },
}))

const Component = (): JSX.Element => <div />
const testLogic = kea<testLogicType>([path(['scenes', 'sceneLogic', 'test'])])
const sceneImport = (): any => ({ scene: { component: Component, logic: testLogic } })

const testScenes: Record<string, () => any> = {
    [Scene.DataManagement]: sceneImport,
    [Scene.Settings]: sceneImport,
}

describe('sceneLogic', () => {
    let logic: ReturnType<typeof sceneLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests()
        localStorage.clear()
        sessionStorage.clear()
        ;(api.get as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
        ;(api.update as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagLogic.mount()
        router.actions.push(urls.eventDefinitions())
        logic = sceneLogic.build({ scenes: testScenes })
        logic.mount()
        await expectLogic(logic).delay(1)
    })

    it('has preloaded some scenes', async () => {
        const preloadedScenes = [Scene.Error404, Scene.ErrorNetwork, Scene.ErrorProjectUnavailable]
        await expectLogic(logic).toMatchValues({
            exportedScenes: truth(
                (obj: Record<string, any>) =>
                    Object.keys(obj).filter((key) => preloadedScenes.includes(key as Scene)).length === 3
            ),
        })
    })

    it('changing URL runs openScene, loadScene and setScene', async () => {
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            sceneId: Scene.DataManagement,
        })
        router.actions.push(urls.settings('user'))
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            sceneId: Scene.Settings,
        })
    })

    it('persists the loaded scenes', async () => {
        const expectedAnnotation = partial({
            component: expect.any(Function),
            logic: expect.any(Function),
        })

        const expectedSettings = partial({
            component: expect.any(Function),
            logic: expect.any(Function),
        })

        await expectLogic(logic).delay(1)

        expect(logic.values.exportedScenes).toMatchObject({
            [Scene.DataManagement]: expectedAnnotation,
        })
        router.actions.push(urls.settings('user'))
        await expectLogic(logic).delay(1)

        expect(logic.values.exportedScenes).toMatchObject({
            [Scene.DataManagement]: expectedAnnotation,
            [Scene.Settings]: expectedSettings,
        })
    })

    describe('/home honors the configured homepage', () => {
        const dashboardHomepage = {
            id: 'homepage-dashboard-42',
            pathname: urls.dashboard(42),
            search: '',
            hash: '',
            title: 'Default dashboard',
            iconType: 'dashboard' as const,
            sceneId: Scene.Dashboard,
            sceneKey: 'dashboard-42',
            sceneParams: { params: {}, searchParams: {}, hashParams: {} },
        }

        it('redirects /home to the configured dashboard homepage', async () => {
            logic.actions.setHomepage(dashboardHomepage)
            router.actions.push(urls.projectHomepage())
            await expectLogic(logic).delay(1)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.dashboard(42))
        })

        it('stays on the launchpad at /home when no homepage is configured', async () => {
            logic.actions.setHomepage(null)
            router.actions.push(urls.projectHomepage())
            await expectLogic(logic).delay(1)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.projectHomepage())
        })

        it('bootstraps the homepage from APP_CONTEXT so a direct /home visit redirects on first paint', async () => {
            logic.unmount()
            const priorAppContext = window.POSTHOG_APP_CONTEXT
            let bootstrappedHomepagePathname = ''
            let redirectedPathname = ''
            try {
                initKeaTests()
                window.POSTHOG_APP_CONTEXT = {
                    ...window.POSTHOG_APP_CONTEXT,
                    homepage: dashboardHomepage,
                } as unknown as AppContext
                ;(api.get as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
                ;(api.update as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
                await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
                featureFlagLogic.mount()
                router.actions.push(urls.eventDefinitions())
                const bootstrappedLogic = sceneLogic.build({ scenes: testScenes })
                bootstrappedLogic.mount()
                // homepage is populated synchronously from APP_CONTEXT — no setHomepage / API round-trip needed.
                bootstrappedHomepagePathname = removeProjectIdIfPresent(
                    bootstrappedLogic.values.homepage?.pathname ?? ''
                )
                router.actions.push(urls.projectHomepage())
                await expectLogic(bootstrappedLogic).delay(1)
                redirectedPathname = removeProjectIdIfPresent(router.values.location.pathname)
            } finally {
                window.POSTHOG_APP_CONTEXT = priorAppContext
            }
            expect(bootstrappedHomepagePathname).toEqual(urls.dashboard(42))
            expect(redirectedPathname).toEqual(urls.dashboard(42))
        })

        it('forwards allow-listed query params onto the homepage redirect and drops the rest', async () => {
            logic.actions.setHomepage(dashboardHomepage)
            router.actions.push(urls.projectHomepage(), { modal: 'feature', other: 'dropped' })
            await expectLogic(logic).delay(1)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.dashboard(42))
            expect(router.values.searchParams).toEqual({ modal: 'feature' })
        })

        it('does not loop when the launchpad is the homepage and a forwarded param is present', async () => {
            logic.actions.setHomepage({
                ...dashboardHomepage,
                id: 'homepage-launchpad',
                pathname: urls.projectHomepage(),
            })
            router.actions.push(urls.projectHomepage(), { modal: 'feature' })
            await expectLogic(logic).delay(1)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.projectHomepage())
            expect(router.values.searchParams).toEqual({ modal: 'feature' })
        })
    })

    // These relocated paths used to dead-end on the 404 scene; guard the redirects that fix that.
    describe('legacy data management path redirects', () => {
        it.each([
            ['/ingestion-warnings', '/data-management/ingestion-warnings'],
            ['/settings/ingestion-warnings', '/data-management/ingestion-warnings'],
            ['/pipeline/ingestion-warnings', '/data-management/ingestion-warnings'],
            ['/data-warehouse', '/data-ops'],
            ['/data-warehouse/posthog', '/data-management/sources'],
            ['/data-warehouse/sources', '/data-management/sources'],
            ['/data-warehouse/settings', '/data-management/sources'],
            ['/data-warehouse/view', '/sql'],
        ])('redirects %s to %s', async (from, to) => {
            router.actions.push(from)
            await expectLogic(logic).delay(1)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(to)
        })
    })
})
