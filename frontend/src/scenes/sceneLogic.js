import React from 'react'
import { kea } from 'kea'
import { router } from 'kea-router'

export const loadedScenes = {
    '404': { component: () => <div>404</div> },
}
const delay = ms => new Promise(resolve => window.setTimeout(resolve, ms))

export const scenes = {
    dashboard: () => import(/* webpackChunkName: 'dashboard' */ './dashboard/Dashboard'),
    events: () => import(/* webpackChunkName: 'events' */ './events/Events'),
    person: () => import(/* webpackChunkName: 'person' */ './users/Person'),
    people: () => import(/* webpackChunkName: 'people' */ './users/People'),
    actions: () => import(/* webpackChunkName: 'actions' */ './actions/Actions'),
    action: () => import(/* webpackChunkName: 'action' */ './actions/Action'),
    liveActions: () => import(/* webpackChunkName: 'liveActions' */ './actions/LiveActions'),
    funnel: () => import(/* webpackChunkName: 'funnel' */ './funnels/Funnel'),
    editFunnel: () => import(/* webpackChunkName: 'editFunnel' */ './funnels/EditFunnel'),
    funnels: () => import(/* webpackChunkName: 'funnels' */ './funnels/Funnels'),
    setup: () => import(/* webpackChunkName: 'setup' */ './setup/Setup'),
    trends: () => import(/* webpackChunkName: 'trends' */ './trends/Trends'),
    paths: () => import(/* webpackChunkName: 'paths' */ './paths/Paths'),
    cohorts: () => import(/* webpackChunkName: 'cohorts' */ './users/Cohorts'),
}

export const redirects = {
    '/': '/trends',
}

export const routes = {
    '/dashboard': 'dashboard',
    '/action/:id': 'action',
    '/action': 'action',
    '/actions/live': 'liveActions',
    '/actions': 'actions',
    '/trends': 'trends',
    '/funnel': 'funnels',
    '/paths': 'paths',
    '/setup': 'setup',
    '/events': 'events',
    '/person_by_id/:id': 'person',
    '/person/:distinctId': 'person',
    '/people': 'people',
    '/people/cohorts': 'cohorts',
    '/new-funnel': 'editFunnel',
    '/funnel/:id': 'funnel',
}

export const sceneLogic = kea({
    actions: () => ({
        loadScene: (scene, params) => ({ scene, params }),
        setScene: (scene, params) => ({ scene, params }),
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
        loadingScene: [
            true,
            {
                [actions.loadScene]: () => true,
                [actions.setScene]: () => false,
            },
        ],
    }),
    urlToAction: ({ actions }) => {
        const mapping = {}

        for (const [paths, redirect] of Object.entries(redirects)) {
            for (const path of paths.split('|')) {
                mapping[path] = params =>
                    router.actions.replace(typeof redirect === 'function' ? redirect(params) : redirect)
            }
        }

        for (const [paths, scene] of Object.entries(routes)) {
            for (const path of paths.split('|')) {
                mapping[path] = params => actions.loadScene(scene, params)
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

            if (!loadedScenes[scene]) {
                const importedScene = await scenes[scene]()
                breakpoint()
                const { default: defaultExport, logic, ...others } = importedScene

                if (defaultExport) {
                    loadedScenes[scene] = {
                        component: defaultExport,
                        logic: logic,
                    }
                } else {
                    loadedScenes[scene] = {
                        component: Object.keys(others).length === 1 ? others[Object.keys(others)[0]] : Error404,
                        logic: logic,
                    }
                }
            }

            const { logic } = loadedScenes[scene]

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
