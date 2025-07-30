import { actions, connect, kea, listeners, reducers, path, afterMount } from 'kea'
import { combineUrl, router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

import type { sceneTabsLogicType } from './sceneTabsLogicType'
import { addProjectIdIfMissing } from 'lib/utils/router-utils'

export interface SceneTab {
    pathname: string
    search: string
    hash: string
    title: string
    active: boolean
    persist: boolean
}

export const sceneTabsLogic = kea<sceneTabsLogicType>([
    path(['layout', 'scenes', 'sceneTabsLogic']),
    connect(() => ({
        actions: [router, ['locationChanged', 'push']],
        values: [breadcrumbsLogic, ['title']],
    })),
    actions({
        setTabs: (tabs: SceneTab[]) => ({ tabs }),
        newTab: true,
        removeTab: (tab: SceneTab) => ({ tab }),
        activateTab: (tab: SceneTab) => ({ tab }),
        persistTab: (tab: SceneTab) => ({ tab }),
        clickOnTab: (tab: SceneTab) => ({ tab }),
    }),
    reducers({
        tabs: [
            [] as SceneTab[],
            {
                setTabs: (_, { tabs }) => tabs,
                newTab: (state) => {
                    return [
                        ...state.map((tab) => ({ ...tab, active: false, persist: true })),
                        {
                            persist: false,
                            active: true,
                            pathname: '/new',
                            search: '',
                            hash: '',
                            title: 'New tab',
                        },
                    ]
                },
                removeTab: (state, { tab }) => {
                    let index = state.findIndex((t) => t === tab)
                    if (index === -1) {
                        console.error('Tab to remove not found', tab)
                        return state
                    }
                    let newState = state.filter((_, i) => i !== index)
                    if (!newState.find((t) => t.active)) {
                        const newActiveIndex = Math.max(index - 1, 0)
                        newState = newState.map((tag, i) => (i === newActiveIndex ? { ...tag, active: true } : tag))
                    }
                    return newState
                },
                persistTab: (state, { tab }) => {
                    return state.map((t) => (t === tab && !t.persist ? { ...t, persist: true } : t))
                },
                activateTab: (state, { tab }) => {
                    return state.map((t) =>
                        t === tab && !t.active ? { ...t, active: true } : t.active ? { ...t, active: false } : t
                    )
                },
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        clickOnTab: ({ tab }) => {
            const clickedIndex = values.tabs.findIndex((t) => t === tab)
            actions.persistTab(tab)
            // Activate before pushing so that the new title would be attributed to the right tab
            if (!values.tabs[clickedIndex]?.active) {
                actions.activateTab(tab)
            }
            router.actions.push(tab.pathname, tab.search, tab.hash)
        },
        push: ({ url, hashInput, searchInput }) => {
            let { pathname, search, hash } = combineUrl(url, searchInput, hashInput)
            pathname = addProjectIdIfMissing(pathname)
            let existingTabIndex = values.tabs.findIndex(
                (tab) => tab.pathname === pathname && tab.search === search && tab.hash === hash && tab.active
            )
            if (existingTabIndex === -1) {
                existingTabIndex = values.tabs.findIndex(
                    (tab) => tab.pathname === pathname && tab.search === search && tab.hash === hash
                )
            }
            if (existingTabIndex !== -1) {
                actions.setTabs(
                    values.tabs.map((tab, i) =>
                        i === existingTabIndex ? { ...tab, active: true } : { ...tab, active: false }
                    )
                )
            } else {
                const notPersistedTabIndex = values.tabs.findIndex((t) => !t.persist)
                if (notPersistedTabIndex === -1) {
                    actions.setTabs([
                        ...values.tabs,
                        {
                            persist: false,
                            active: true,
                            pathname,
                            search,
                            hash,
                            title: 'Loading...',
                        },
                    ])
                } else {
                    actions.setTabs(
                        values.tabs.map((tab, i) =>
                            i === notPersistedTabIndex
                                ? { ...tab, active: true, pathname, search, hash }
                                : { ...tab, active: false }
                        )
                    )
                }
            }
        },
        locationChanged: ({ pathname, search, hash, method }) => {
            if (method === 'REPLACE') {
                const activeTabIndex = values.tabs.findIndex((tab) => tab.active)
                const notPersistedTabIndex = values.tabs.findIndex((tab) => !tab.persist)
                if (activeTabIndex === -1) {
                    if (notPersistedTabIndex === -1) {
                        actions.setTabs([
                            ...values.tabs,
                            {
                                persist: false,
                                active: true,
                                pathname,
                                search,
                                hash,
                                title: 'Loading...',
                            },
                        ])
                    } else {
                        actions.setTabs(
                            values.tabs.map((tab, i) =>
                                i === notPersistedTabIndex
                                    ? {
                                          ...tab,
                                          active: true,
                                          pathname,
                                          search,
                                          hash,
                                      }
                                    : { ...tab, active: false }
                            )
                        )
                    }
                } else {
                    actions.setTabs(
                        values.tabs.map((tab, i) =>
                            i === activeTabIndex ? { ...tab, pathname, search, hash } : { ...tab, active: false }
                        )
                    )
                }
            } else if (method === 'PUSH' || method === 'POP') {
                const existingTabIndex = values.tabs.findIndex(
                    (tab) => tab.pathname === pathname && tab.search === search && tab.hash === hash
                )
                if (existingTabIndex !== -1) {
                    actions.setTabs(
                        values.tabs.map((tab, i) =>
                            i === existingTabIndex ? { ...tab, active: true } : { ...tab, active: false }
                        )
                    )
                } else {
                    const notPersistedTabIndex = values.tabs.findIndex((t) => !t.persist)
                    if (notPersistedTabIndex === -1) {
                        actions.setTabs([
                            ...values.tabs,
                            {
                                persist: false,
                                active: true,
                                pathname,
                                search,
                                hash,
                                title: 'Loading...',
                            },
                        ])
                    } else {
                        actions.setTabs(
                            values.tabs.map((tab, i) =>
                                i === notPersistedTabIndex
                                    ? { ...tab, active: true, pathname, search, hash }
                                    : { ...tab, active: false }
                            )
                        )
                    }
                }
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        title: (title) => {
            const activeIndex = values.tabs.findIndex((t) => t.active)
            if (activeIndex === -1) {
                const { currentLocation } = router.values
                actions.setTabs([
                    {
                        persist: false,
                        active: true,
                        pathname: currentLocation.pathname,
                        search: currentLocation.search,
                        hash: currentLocation.hash,
                        title,
                    },
                ])
            } else {
                actions.setTabs(values.tabs.map((tab, i) => (i === activeIndex ? { ...tab, title } : tab)))
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.tabs.length === 0) {
            const { currentLocation } = router.values
            actions.setTabs([
                {
                    persist: false,
                    active: true,
                    pathname: currentLocation.pathname,
                    search: currentLocation.search,
                    hash: currentLocation.hash,
                    title: 'Loading...',
                },
            ])
        }
    }),
])
