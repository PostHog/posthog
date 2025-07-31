import { actions, connect, kea, listeners, reducers, path, afterMount } from 'kea'
import { combineUrl, router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { arrayMove } from '@dnd-kit/sortable'

import type { sceneTabsLogicType } from './sceneTabsLogicType'
import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

export interface SceneTab {
    id: string
    pathname: string
    search: string
    hash: string
    title: string
    active: boolean
}

const TAB_STATE_KEY = 'scene-tabs-state'
const persistTabs = (tabs: SceneTab[]): void => {
    sessionStorage.setItem(TAB_STATE_KEY, JSON.stringify(tabs))
}
const getPersistedTabs: () => SceneTab[] | null = () => {
    const savedTabs = sessionStorage.getItem(TAB_STATE_KEY)
    if (savedTabs) {
        try {
            return JSON.parse(savedTabs)
        } catch (e) {
            console.error('Failed to parse saved tabs from sessionStorage:', e)
        }
    }
    return null
}
const generateTabId = (): string => crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`

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
        clickOnTab: (tab: SceneTab) => ({ tab }),
        reorderTabs: (activeId: string, overId: string) => ({ activeId, overId }),
    }),
    reducers({
        tabs: [
            [] as SceneTab[],
            {
                setTabs: (_, { tabs }) => tabs,
                newTab: (state) => {
                    return [
                        ...state.map((tab) => (tab.active ? { ...tab, active: false } : tab)),
                        {
                            id: generateTabId(),
                            active: true,
                            pathname: addProjectIdIfMissing('/new'),
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
                activateTab: (state, { tab }) => {
                    const newState = state.map((t) =>
                        t === tab
                            ? !t.active
                                ? { ...t, active: true }
                                : t
                            : t.active
                            ? {
                                  ...t,
                                  active: false,
                              }
                            : t
                    )
                    return newState
                },
                reorderTabs: (state, { activeId, overId }) => {
                    const oldIndex = state.findIndex((t) => t.id === activeId)
                    const newIndex = state.findIndex((t) => t.id === overId)
                    if (oldIndex === -1 || newIndex === -1 || oldIndex === newIndex) {
                        return state
                    }
                    return arrayMove(state, oldIndex, newIndex)
                },
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        setTabs: () => persistTabs(values.tabs),
        newTab: () => {
            persistTabs(values.tabs)
            router.actions.push(urls.newTab())
        },
        activateTab: () => persistTabs(values.tabs),
        removeTab: ({ tab }) => {
            if (tab.active) {
                const activeTab = values.tabs.find((tab) => tab.active)
                if (activeTab) {
                    router.actions.push(activeTab.pathname, activeTab.search, activeTab.hash)
                } else {
                    persistTabs(values.tabs)
                }
            } else {
                persistTabs(values.tabs)
            }
        },
        clickOnTab: ({ tab }) => {
            if (!tab.active) {
                actions.activateTab(tab)
            }
            router.actions.push(tab.pathname, tab.search, tab.hash)
            persistTabs(values.tabs)
        },
        reoderTabs: () => {
            persistTabs(values.tabs)
        },
        push: ({ url, hashInput, searchInput }) => {
            let { pathname, search, hash } = combineUrl(url, searchInput, hashInput)
            pathname = addProjectIdIfMissing(pathname)

            const activeTabIndex = values.tabs.findIndex((tab) => tab.active)
            if (activeTabIndex !== -1) {
                const newTabs = values.tabs.map((tab, i) =>
                    i === activeTabIndex
                        ? { ...tab, active: true, pathname, search, hash }
                        : tab.active
                        ? {
                              ...tab,
                              active: false,
                          }
                        : tab
                )

                actions.setTabs(newTabs)
            } else {
                actions.setTabs([
                    ...values.tabs,
                    { id: generateTabId(), active: true, pathname, search, hash, title: 'Loading...' },
                ])
            }
            persistTabs(values.tabs)
        },
        locationChanged: ({ pathname, search, hash, routerState }) => {
            pathname = addProjectIdIfMissing(pathname)
            if (routerState?.tabs) {
                actions.setTabs(routerState.tabs)
                return
            }
            const activeTabIndex = values.tabs.findIndex((tab) => tab.active)
            if (activeTabIndex !== -1) {
                actions.setTabs(
                    values.tabs.map((tab, i) =>
                        i === activeTabIndex
                            ? { ...tab, active: true, pathname, search, hash }
                            : tab.active
                            ? {
                                  ...tab,
                                  active: false,
                              }
                            : tab
                    )
                )
            } else {
                actions.setTabs([
                    ...values.tabs,
                    { id: generateTabId(), active: true, pathname, search, hash, title: 'Loading...' },
                ])
            }
            persistTabs(values.tabs)
        },
    })),
    subscriptions(({ actions, values, cache }) => ({
        title: (title) => {
            // this fires before afterMount below, so... doing the logic here
            if (!cache.tagsLoaded) {
                const savedTabs = getPersistedTabs()
                const withIds = savedTabs?.map((t) => (t.id ? t : { ...t, id: generateTabId() }))
                if (withIds) {
                    actions.setTabs(withIds)
                }
                cache.tagsLoaded = true
            }

            const activeIndex = values.tabs.findIndex((t) => t.active)
            if (activeIndex === -1) {
                const { currentLocation } = router.values
                actions.setTabs([
                    {
                        id: generateTabId(),
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
    afterMount(({ actions, cache, values }) => {
        // this logic is fired above in "title", but keeping here just in case
        if (!cache.tagsLoaded) {
            const savedTabs = getPersistedTabs()
            const withIds = savedTabs?.map((t) => (t.id ? t : { ...t, id: generateTabId() }))
            if (withIds) {
                actions.setTabs(withIds)
            }
            cache.tagsLoaded = true
        }
        if (values.tabs.length === 0) {
            const { currentLocation } = router.values
            actions.setTabs([
                {
                    id: generateTabId(),
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
