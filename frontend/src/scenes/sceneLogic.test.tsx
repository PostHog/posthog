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
import { AccessControlLevel, AccessControlResourceType, type AppContext } from '~/types'

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
    [Scene.Alerts]: sceneImport,
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

    it('redirects the hyphenated /feature-flags path to the underscore scene route', async () => {
        router.actions.push('/feature-flags')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.featureFlags())

        router.actions.push('/feature-flags/123')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.featureFlag('123'))
    })

    it('redirects /project/new to the create-project flow instead of a 404', async () => {
        router.actions.push('/project/new')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.projectCreateFirst())
    })

    it('redirects /data-warehouse/new to the new-source wizard instead of a 404', async () => {
        router.actions.push('/data-warehouse/new')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.dataWarehouseSourceNew())
    })

    it('redirects the old /code_review path to /code-review, preserving the ?review= deep link and hash', async () => {
        router.actions.push('/code_review', { review: 'r-9' }, { panel: 'max:inspect' })
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.codeReview())
        // ?review=<report id> is a permanent public contract baked into GitHub PR comments — the
        // redirect must carry it across so those links keep opening the right report. The hash
        // carries global side-panel state, so it has to survive the redirect too.
        expect(router.values.searchParams.review).toEqual('r-9')
        expect(router.values.hashParams.panel).toEqual('max:inspect')
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

    it('does not blanket deny the combined alerts scene without insight access', async () => {
        const priorAppContext = window.POSTHOG_APP_CONTEXT
        try {
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                effective_resource_access_control: {
                    ...window.POSTHOG_APP_CONTEXT?.effective_resource_access_control,
                    [AccessControlResourceType.Insight]: AccessControlLevel.None,
                },
            } as AppContext

            logic.actions.setScene(Scene.Alerts, 'alerts', { params: {}, searchParams: {}, hashParams: {} })

            await expectLogic(logic).toMatchValues({
                sceneId: Scene.Alerts,
                activeSceneId: Scene.Alerts,
            })
        } finally {
            window.POSTHOG_APP_CONTEXT = priorAppContext
        }
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

        // A homepage saved against a since-removed scene must be dropped, not followed. Following it
        // sends every `/` visit to a dead route, and once that route has a compatibility redirect
        // pointing back home the two bounce off each other forever.
        it('ignores a bootstrapped homepage whose scene no longer ships', async () => {
            logic.unmount()
            const priorAppContext = window.POSTHOG_APP_CONTEXT
            let hadBootstrappedHomepage = true
            let redirectedPathname = ''
            try {
                initKeaTests()
                window.POSTHOG_APP_CONTEXT = {
                    ...window.POSTHOG_APP_CONTEXT,
                    homepage: {
                        ...dashboardHomepage,
                        id: 'homepage-removed-scene',
                        pathname: '/removed-scene',
                        sceneId: 'RemovedScene',
                    },
                } as unknown as AppContext
                ;(api.get as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
                ;(api.update as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
                await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
                featureFlagLogic.mount()
                router.actions.push(urls.eventDefinitions())
                const bootstrappedLogic = sceneLogic.build({ scenes: testScenes })
                bootstrappedLogic.mount()
                hadBootstrappedHomepage = bootstrappedLogic.values.homepage !== null
                router.actions.push(urls.projectHomepage())
                await expectLogic(bootstrappedLogic).delay(1)
                redirectedPathname = removeProjectIdIfPresent(router.values.location.pathname)
            } finally {
                window.POSTHOG_APP_CONTEXT = priorAppContext
            }
            expect(hadBootstrappedHomepage).toBe(false)
            expect(redirectedPathname).toEqual(urls.projectHomepage())
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

        // Regression guard: `/#panel=max:<prompt>` pre-fills the Max side panel, but only if the
        // hash survives the `/` → homepage redirect. It used to be dropped, so the prompt was lost
        // on the Home scene (yet worked everywhere else, which have no such redirect).
        it.each([
            ['no homepage is configured', null, urls.projectHomepage()],
            ['a dashboard homepage is configured', dashboardHomepage, urls.dashboard(42)],
        ])('preserves the #panel hash across the / redirect when %s', async (_desc, homepage, expectedPathname) => {
            logic.actions.setHomepage(homepage)
            router.actions.push('/', {}, { panel: 'max:what is my dau' })
            await expectLogic(logic).delay(1)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(expectedPathname)
            expect(router.values.hashParams).toEqual({ panel: 'max:what is my dau' })
        })

        // A configured homepage can carry its own hash (e.g. a dashboard tab). Forwarding the
        // incoming hash must merge over that, not replace it — so an empty incoming hash keeps the
        // configured one, and a `#panel` hash is added alongside it.
        it.each([
            ['no incoming hash', {}, { tab: 'configured' }],
            ['an incoming #panel hash', { panel: 'max:hi' }, { tab: 'configured', panel: 'max:hi' }],
        ])(
            'keeps a configured homepage hash across the / redirect with %s',
            async (_desc, incomingHash, expectedHash) => {
                logic.actions.setHomepage({ ...dashboardHomepage, hash: '#tab=configured' })
                router.actions.push('/', {}, incomingHash)
                await expectLogic(logic).delay(1)
                expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.dashboard(42))
                expect(router.values.hashParams).toEqual(expectedHash)
            }
        )
    })
})
