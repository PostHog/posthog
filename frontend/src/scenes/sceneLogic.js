import { kea } from 'kea'
import { router } from 'kea-router'
import { delay } from 'lib/utils'
import { Error404 } from '~/layout/Error404'

export const scenes = {
    // NB! also update sceneOverride in layout/Sidebar.js if adding new scenes that belong to an old sidebar link

    dashboards: () => import(/* webpackChunkName: 'dashboard' */ './dashboard/Dashboards'),
    dashboard: () => import(/* webpackChunkName: 'dashboard' */ './dashboard/Dashboard'),
    events: () => import(/* webpackChunkName: 'events' */ './events/Events'),
    sessions: () => import(/* webpackChunkName: 'events' */ './sessions/Sessions'),
    person: () => import(/* webpackChunkName: 'person' */ './users/Person'),
    people: () => import(/* webpackChunkName: 'people' */ './users/People'),
    actions: () => import(/* webpackChunkName: 'actions' */ './actions/Actions'),
    action: () => import(/* webpackChunkName: 'action' */ './actions/Action'),
    liveActions: () => import(/* webpackChunkName: 'liveActions' */ './actions/LiveActions'),
    editFunnel: () => import(/* webpackChunkName: 'editFunnel' */ './funnels/Funnel'),
    funnels: () => import(/* webpackChunkName: 'funnels' */ './funnels/Funnels'),
    setup: () => import(/* webpackChunkName: 'setup' */ './setup/Setup'),
    insights: () => import(/* webpackChunkName: 'insights' */ './insights/Insights'),
    cohorts: () => import(/* webpackChunkName: 'cohorts' */ './users/Cohorts'),
    featureFlags: () => import(/* webpackChunkName: 'featureFlags' */ './experiments/FeatureFlags'),
    annotations: () => import(/* webpackChunkName: 'annotations' */ './annotations/AnnotationsScene'),
    team: () => import(/* webpackChunkName: 'team' */ './team/Team'),
}

export const redirects = {
    '/': '/insights',
}

export const routes = {
    '/dashboard': 'dashboards',
    '/dashboard/:id': 'dashboard',
    '/action/:id': 'action',
    '/action': 'action',
    '/actions/live': 'liveActions',
    '/actions': 'actions',
    '/insights': 'insights',
    '/funnel': 'funnels',
    '/funnel/new': 'editFunnel',
    '/setup': 'setup',
    '/events': 'events',
    '/person_by_id/:id': 'person',
    '/person/*': 'person',
    '/people': 'people',
    '/people/new_cohort': 'people',
    '/people/cohorts': 'cohorts',
    '/experiments/feature_flags': 'featureFlags',
    '/sessions': 'sessions',
    '/annotations': 'annotations',
    '/team': 'team',
}

export const sceneLogic = kea({
    actions: () => ({
        loadScene: (scene, params) => ({ scene, params }),
        setScene: (scene, params) => ({ scene, params }),
        setLoadedScene: (scene, loadedScene) => ({ scene, loadedScene }),
    }),
    reducers: ({ actions }) => ({
        scene: [
            null,
            {
                [actions.setScene]: (_, payload) => payload.scene,
            },
        ],
        params: [
            {},
            {
                [actions.setScene]: (_, payload) => payload.params || {},
            },
        ],
        loadedScenes: [
            {
                '404': {
                    component: Error404,
                },
            },
            {
                [actions.setLoadedScene]: (state, { scene, loadedScene }) => ({ ...state, [scene]: loadedScene }),
            },
        ],
        loadingScene: [
            null,
            {
                [actions.loadScene]: (_, { scene }) => scene,
                [actions.setScene]: () => null,
            },
        ],
    }),
    urlToAction: ({ actions }) => {
        const mapping = {}

        for (const [paths, redirect] of Object.entries(redirects)) {
            for (const path of paths.split('|')) {
                mapping[path] = (params) =>
                    router.actions.replace(typeof redirect === 'function' ? redirect(params) : redirect)
            }
        }

        for (const [paths, scene] of Object.entries(routes)) {
            for (const path of paths.split('|')) {
                mapping[path] = (params) => actions.loadScene(scene, params)
            }
        }
        mapping['/*'] = () => actions.loadScene('404', {})

        return mapping
    },
    listeners: ({ values, actions }) => ({
        setScene: () => {
            window.posthog && window.posthog.capture('$pageview')
        },
        loadScene: async ({ scene, params = {} }, breakpoint) => {
            if (values.scene === scene) {
                actions.setScene(scene, params)
                return
            }

            if (!scenes[scene]) {
                actions.setScene('404', {})
                return
            }

            let loadedScene = values.loadedScenes[scene]

            if (!loadedScene) {
                const importedScene = await scenes[scene]()
                breakpoint()
                const { default: defaultExport, logic, ...others } = importedScene

                if (defaultExport) {
                    loadedScene = {
                        component: defaultExport,
                        logic: logic,
                    }
                } else {
                    loadedScene = {
                        component:
                            Object.keys(others).length === 1
                                ? others[Object.keys(others)[0]]
                                : values.loadedScenes['404'].component,
                        logic: logic,
                    }
                }
                actions.setLoadedScene(scene, loadedScene)
            }

            const { logic } = loadedScene

            let unmount

            if (logic) {
                // initialize the logic
                unmount = logic.build(params, false).mount()
                try {
                    await breakpoint(100)
                } catch (e) {
                    // if we change the scene while waiting these 100ms, unmount
                    unmount()
                    throw e
                }
            }

            actions.setScene(scene, params)

            if (unmount) {
                // release our hold on this logic after 0.5s as it's by then surely mounted via React
                // or we are anyway in a new scene and don't need it
                await delay(500)
                unmount()
            }
        },
    }),
})
