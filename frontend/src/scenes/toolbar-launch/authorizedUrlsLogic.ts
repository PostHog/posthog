import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { appEditorUrl } from 'lib/components/AppEditorLink/utils'
import { TrendResult } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs } from 'lib/dayjs'
import Fuse from 'fuse.js'
import { authorizedUrlsLogicType } from './authorizedUrlsLogicType'

export interface KeyedAppUrl {
    url: string
    type: 'authorized' | 'suggestion'
}

const defaultValue = 'https://'

export const authorizedUrlsLogic = kea<authorizedUrlsLogicType<KeyedAppUrl>>({
    path: ['lib', 'components', 'AppEditorLink', 'appUrlsLogic'],
    props: {} as {
        actionId?: number
    },
    connect: {
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    },
    actions: () => ({
        setAppUrls: (appUrls: string[]) => ({ appUrls }),
        addUrl: (url: string, launch?: boolean) => ({ url, launch }),
        removeUrl: (index: number) => ({ index }),
        updateUrl: (index: number, url: string) => ({ index, url }),
        launchAtUrl: (url: string) => ({ url }),
        setPopoverOpen: (indexedUrl: string | null) => ({ indexedUrl }),
        setSearchTerm: (term: string) => ({ term }),
    }),

    loaders: ({ values }) => ({
        suggestions: {
            __default: [] as string[],
            loadSuggestions: async () => {
                const params = {
                    events: [{ id: '$pageview', name: '$pageview', type: 'events' }],
                    breakdown: '$current_url',
                    date_from: dayjs().subtract(3, 'days').toISOString(),
                }
                const result = (
                    await api.get(`api/projects/${values.currentTeamId}/insights/trend/?${toParams(params)}`)
                ).result as TrendResult[]
                if (result && result[0]?.count === 0) {
                    return []
                }
                const domainsSeen: string[] = []
                return (result || [])
                    .filter((item) => {
                        if (!item.breakdown_value) {
                            return false
                        }
                        try {
                            const domain = new URL(item.breakdown_value.toString()).hostname
                            if (domainsSeen.indexOf(domain) > -1) {
                                return
                            }
                            if (values.appUrls.filter((url) => url.indexOf(domain) > -1).length > 0) {
                                return
                            }
                            domainsSeen.push(domain)
                            return true
                        } catch (error) {
                            return false
                        }
                    })
                    .map((item) => item.breakdown_value)
                    .slice(0, 20)
            },
        },
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            actions.loadSuggestions()
            if (values.currentTeam) {
                actions.setAppUrls(values.currentTeam.app_urls)
            }
        },
    }),
    reducers: () => ({
        appUrls: [
            [] as string[],
            {
                setAppUrls: (_, { appUrls }) => appUrls,
                addUrl: (state, { url }) => state.concat([url || defaultValue]),
                updateUrl: (state, { index, url }) => Object.assign([...state], { [index]: url }),
                removeUrl: (state, { index }) => {
                    const newAppUrls = [...state]
                    newAppUrls.splice(index, 1)
                    return newAppUrls
                },
            },
        ],
        suggestions: [
            [],
            {
                addUrl: (state, { url }) => [...state].filter((item) => url !== item),
            },
        ],
        popoverOpen: [
            // Used in ToolbarLaunch.tsx to determine if the "..." more menu popover is shown for an item
            null as string | null,
            {
                setPopoverOpen: (_, { indexedUrl }) => indexedUrl,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
            },
        ],
    }),
    listeners: ({ sharedListeners, props, actions }) => ({
        addUrl: [
            sharedListeners.saveAppUrls,
            async ({ url, launch }) => {
                if (launch) {
                    actions.launchAtUrl(url)
                }
            },
        ],
        removeUrl: sharedListeners.saveAppUrls,
        updateUrl: sharedListeners.saveAppUrls,
        [teamLogic.actionTypes.loadCurrentTeamSuccess]: async ({ currentTeam }) => {
            if (currentTeam) {
                actions.setAppUrls(currentTeam.app_urls)
            }
        },
        launchAtUrl: ({ url }) => {
            window.location.href = appEditorUrl(url, props.actionId)
        },
    }),
    sharedListeners: ({ values }) => ({
        saveAppUrls: () => {
            teamLogic.actions.updateCurrentTeam({ app_urls: values.appUrls })
        },
    }),
    selectors: {
        appUrlsKeyed: [
            (s) => [s.appUrls, s.suggestions, s.searchTerm],
            (appUrls, suggestions, searchTerm): KeyedAppUrl[] => {
                const urls = appUrls
                    .map((url) => ({
                        url,
                        type: 'authorized',
                    }))
                    .concat(
                        suggestions.map((url) => ({
                            url,
                            type: 'suggestion',
                        }))
                    ) as KeyedAppUrl[]

                if (!searchTerm) {
                    return urls
                }

                return new Fuse(urls, {
                    keys: ['url'],
                    threshold: 0.3,
                })
                    .search(searchTerm)
                    .map((result) => result.item)
            },
        ],
    },
})
