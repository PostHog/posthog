import { MOCK_USER_UUID } from 'lib/api.mock'

import { kea, path } from 'kea'
import { router } from 'kea-router'
import { expectLogic, partial, testUtilsContext, truth } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import * as exporterViewLogic from '~/exporter/exporterViewLogic'
import { useMocks } from '~/mocks/jest'
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
    [Scene.Billing]: sceneImport,
    [Scene.DataManagement]: sceneImport,
    [Scene.OrganizationCreateFirst]: sceneImport,
    [Scene.PasswordResetComplete]: sceneImport,
    [Scene.ProjectCreateFirst]: sceneImport,
    [Scene.Settings]: sceneImport,
    [Scene.ProjectFiles]: sceneImport,
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

    it('keeps teamLogic mounted after every other mount reference is released', () => {
        // openScene and activeSceneId read teamLogic.values directly. Without a mount reference of
        // its own, navigation throws as soon as nothing else holds teamLogic up.
        teamLogic.unmount()
        expect(teamLogic.isMounted()).toBe(true)
    })

    it.each([
        [urls.settings('user'), Scene.Settings],
        [urls.projectFiles(), Scene.ProjectFiles],
        [urls.projectFiles('Research'), Scene.ProjectFiles],
    ])('changing URL to %s loads its own scene', async (url, sceneId) => {
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            sceneId: Scene.DataManagement,
        })
        router.actions.push(url)
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            sceneId,
        })
    })

    // A trailing slash used to reach the scene, then get replaced out of the address bar. That
    // second navigation re-ran every `urlToAction` of the scene, so the OAuth consent screen
    // reloaded its data and blanked while the person was reading it.
    it('opens a scene once when the URL carries a trailing slash', async () => {
        router.actions.push(urls.settings('user'))
        await expectLogic(logic).delay(1)

        const from = testUtilsContext().recordedHistory.length
        router.actions.push(`${urls.eventDefinitions()}/`)
        await expectLogic(logic).delay(1)
        const openScenes = testUtilsContext()
            .recordedHistory.slice(from)
            .filter((recorded) => recorded.action.type === logic.actionTypes.openScene)

        expect(openScenes).toHaveLength(1)
        expect(logic.values.activeSceneId).toEqual(Scene.DataManagement)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.eventDefinitions())
    })

    it('redirects the hyphenated /feature-flags path to the underscore scene route', async () => {
        router.actions.push('/feature-flags')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.featureFlags())

        router.actions.push('/feature-flags/123')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.featureFlag('123'))
    })

    it('redirects a bare /billing to /organization/billing instead of a 404', async () => {
        router.actions.push('/billing')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.organizationBilling())
    })

    it('keeps /billing/authorization_status on its own scene route, not the billing redirect', async () => {
        router.actions.push(urls.billingAuthorizationStatus())
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.billingAuthorizationStatus())
    })

    it.each([
        ['/organization', urls.settings('organization'), Scene.Settings],
        ['/organization/projects', urls.settings('organization'), Scene.Settings],
        ['/organization/settings/projects', urls.settings('organization'), Scene.Settings],
        ['/organization/projects/new', urls.projectCreateFirst(), Scene.ProjectCreateFirst],
        ['/organization/create', urls.organizationCreateFirst(), Scene.OrganizationCreateFirst],
        ['/organization/new', urls.organizationCreateFirst(), Scene.OrganizationCreateFirst],
    ])('sends the unrouted %s to %s instead of the 404 scene', async (path, expected, expectedScene) => {
        router.actions.push(path)
        await expectLogic(logic).delay(1)
        expect(logic.values.activeSceneId).toEqual(expectedScene)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(expected)
    })

    // The redirect table is keyed on exact paths, so a later `/organization/*` prefix entry would
    // shadow the real scenes under it.
    it('keeps /organization/billing on its own scene route, not the organization redirect', async () => {
        router.actions.push(urls.organizationBilling())
        await expectLogic(logic).delay(1)
        // The `/*` fallback leaves the pathname alone, so only the scene tells a shadowed route apart
        // from a served one.
        expect(logic.values.activeSceneId).toEqual(Scene.Billing)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.organizationBilling())
    })

    it('redirects /project/new to the create-project flow instead of a 404', async () => {
        router.actions.push('/project/new')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.projectCreateFirst())
    })

    it.each(['/project', '/project/'])('sends the id-less %s path to the homepage, not a 404', async (path) => {
        router.actions.push(path)
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.projectHomepage())
    })

    it('redirects /data-warehouse/new to the new-source wizard instead of a 404', async () => {
        router.actions.push('/data-warehouse/new')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.dataWarehouseSourceNew())
    })

    it('sends a guessed /replay/vision to replay vision, not the recording-not-found scene', async () => {
        // `/replay/:id` would otherwise match and read `vision` as a recording id.
        router.actions.push('/replay/vision')
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.replayVision())
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

    it.each([
        ['the product root', () => '/engineering-analytics', () => urls.engineeringAnalytics()],
        [
            'the project-prefixed test health path',
            (projectId: number) => `/project/${projectId}/engineering-analytics/test-health`,
            () => urls.engineeringAnalyticsTests(),
        ],
        ['the health path', () => '/engineering-analytics/health', () => urls.engineeringAnalyticsDeploys()],
    ])('redirects %s without dropping scope or hash', async (_label, oldPath, newPath) => {
        const projectId = teamLogic.values.currentTeamId
        router.actions.push(
            oldPath(projectId),
            { source: 'source-1', repo: 'PostHog/posthog' },
            { panel: 'max:inspect' }
        )
        await expectLogic(logic).delay(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(newPath())
        expect(router.values.location.pathname).toEqual(`/project/${projectId}${newPath()}`)
        expect(router.values.searchParams).toMatchObject({ source: 'source-1', repo: 'PostHog/posthog' })
        expect(router.values.hashParams.panel).toEqual('max:inspect')
    })

    // The change password form emails this link to a user who is already signed in.
    it('keeps a signed-in user on the password reset link instead of redirecting them away', async () => {
        const resetLink = urls.passwordResetComplete(MOCK_USER_UUID, 'a-token')
        router.actions.push(resetLink)
        await expectLogic(logic).delay(1)

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(resetLink)
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

    // The third case is a legacy project token, which matches no route on its own.
    test.each(['12345', 'phc_12345', 'aBcDeFgHiJkLmN'])(
        'renders the project access denied scene while the address names the refused project %s',
        async (refusedProject) => {
            const priorAppContext = window.POSTHOG_APP_CONTEXT
            try {
                window.POSTHOG_APP_CONTEXT = {
                    ...window.POSTHOG_APP_CONTEXT,
                    project_access_denied: refusedProject,
                } as AppContext

                router.actions.push(`/project/${refusedProject}/settings/user`)
                await expectLogic(logic).delay(1)
                expect(logic.values.activeSceneId).toEqual(Scene.ErrorProjectAccessDenied)

                // Later navigations run against the project we do serve.
                router.actions.push(urls.settings('user'))
                await expectLogic(logic).delay(1)
                expect(logic.values.activeSceneId).toEqual(Scene.Settings)
            } finally {
                window.POSTHOG_APP_CONTEXT = priorAppContext
            }
        }
    )

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

        it('confirms a homepage change only after the save succeeds', async () => {
            const sharedView = jest.spyOn(exporterViewLogic, 'isSharedView').mockReturnValue(false)
            const successToast = jest.spyOn(lemonToast, 'success').mockReturnValue('toast-id')
            const capture = jest.spyOn(posthog, 'capture')
            let finishSave!: () => void
            let startSave!: () => void
            const saveResponse = new Promise<void>((resolve) => (finishSave = resolve))
            const saveStarted = new Promise<void>((resolve) => (startSave = resolve))
            useMocks({
                patch: {
                    '/api/user_home_settings/@me/': async () => {
                        startSave()
                        await saveResponse
                        return [200, {}] as const
                    },
                },
            })

            const previousHomepage = logic.values.homepage
            logic.actions.setHomepage(dashboardHomepage, 'dashboards list')
            expect(logic.values.homepage).toEqual(previousHomepage)
            expect(logic.values.homepageSaving).toBe(true)
            await saveStarted
            finishSave()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.homepage?.id).toBe(dashboardHomepage.id)
            expect(logic.values.homepageSaving).toBe(false)
            expect(successToast).toHaveBeenCalledWith('Homepage updated')
            expect(capture).toHaveBeenCalledWith('dashboard set as homepage', { source: 'dashboards list' })
            capture.mockRestore()
            successToast.mockRestore()
            sharedView.mockRestore()
        })

        it('keeps the previous homepage if saving from the dashboard list fails', async () => {
            const sharedView = jest.spyOn(exporterViewLogic, 'isSharedView').mockReturnValue(false)
            const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('toast-id')
            const errorLog = jest.spyOn(console, 'error').mockImplementation()
            useMocks({ patch: { '/api/user_home_settings/@me/': [500, {}] } })
            const previousHomepage = logic.values.homepage

            await expectLogic(logic, () =>
                logic.actions.setHomepage(dashboardHomepage, 'dashboards list')
            ).toFinishAllListeners()

            expect(logic.values.homepage).toEqual(previousHomepage)
            expect(logic.values.homepageSaving).toBe(false)
            expect(errorToast).toHaveBeenCalledWith('Could not save your homepage. Please try again.')
            errorLog.mockRestore()
            errorToast.mockRestore()
            sharedView.mockRestore()
        })

        it('ignores overlapping dashboard-list homepage saves', async () => {
            const sharedView = jest.spyOn(exporterViewLogic, 'isSharedView').mockReturnValue(false)
            let finishSave!: () => void
            let startSave!: () => void
            const saveResponse = new Promise<void>((resolve) => (finishSave = resolve))
            const saveStarted = new Promise<void>((resolve) => (startSave = resolve))
            const saveHandler = jest.fn(async () => {
                startSave()
                await saveResponse
                return [200, {}] as const
            })
            useMocks({ patch: { '/api/user_home_settings/@me/': saveHandler } })

            logic.actions.setHomepage(dashboardHomepage, 'dashboards list')
            logic.actions.setHomepage(
                { ...dashboardHomepage, id: 'homepage-dashboard-43', pathname: urls.dashboard(43) },
                'dashboards list'
            )
            await saveStarted
            expect(saveHandler).toHaveBeenCalledTimes(1)
            finishSave()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.homepage?.id).toBe(dashboardHomepage.id)
            sharedView.mockRestore()
        })

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

        it('drops a homepage whose object turned out not to exist, and lands on the launchpad', async () => {
            logic.actions.setHomepage(dashboardHomepage)
            router.actions.push(urls.projectHomepage())
            await expectLogic(logic).delay(1)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.dashboard(42))

            logic.actions.resetUnavailableHomepage(urls.dashboard(42))
            await expectLogic(logic).delay(1)

            expect(logic.values.homepage).toBeNull()
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.projectHomepage())
        })

        // The way out of the dead end must keep the URL state the `/` → homepage redirect already
        // forwards, or a modal bound to `?modal=` closes itself as the person lands on the launchpad.
        it('carries the hash and allow-listed params onto the launchpad when it drops the homepage', async () => {
            logic.actions.setHomepage(dashboardHomepage)
            router.actions.push(urls.projectHomepage(), { modal: 'invite-members' }, { panel: 'max:hi' })
            await expectLogic(logic).delay(1)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.dashboard(42))

            logic.actions.resetUnavailableHomepage(urls.dashboard(42))
            await expectLogic(logic).delay(1)

            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.projectHomepage())
            expect(router.values.searchParams).toEqual({ modal: 'invite-members' })
            expect(router.values.hashParams).toEqual({ panel: 'max:hi' })
        })

        // The reset fires from whichever logic found its object missing, and dashboard logics are
        // also mounted embedded — in notebooks, on the feature flag page — so a missing object that
        // is not the homepage must leave both the setting and the address bar alone.
        it('keeps the homepage when some other object is the missing one', async () => {
            logic.actions.setHomepage(dashboardHomepage)
            router.actions.push(urls.dashboard(99))
            await expectLogic(logic).delay(1)

            logic.actions.resetUnavailableHomepage(urls.dashboard(99))
            await expectLogic(logic).delay(1)

            expect(logic.values.homepage?.pathname).toEqual(urls.dashboard(42))
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.dashboard(99))
        })

        // Clearing the setting is right wherever the homepage dashboard was found missing, but
        // navigating away is only right when that dashboard is what fills the screen.
        it('drops the homepage without navigating when it is missing from an embedded render', async () => {
            logic.actions.setHomepage(dashboardHomepage)
            router.actions.push(urls.notebook('abc'))
            await expectLogic(logic).delay(1)

            logic.actions.resetUnavailableHomepage(urls.dashboard(42))
            await expectLogic(logic).delay(1)

            expect(logic.values.homepage).toBeNull()
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.notebook('abc'))
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
