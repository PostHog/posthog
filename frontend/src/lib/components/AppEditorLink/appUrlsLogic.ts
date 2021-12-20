import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { appEditorUrl } from 'lib/components/AppEditorLink/utils'
import { appUrlsLogicType } from './appUrlsLogicType'
import { TrendResult } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs } from 'lib/dayjs'

export interface KeyedAppUrl {
    url: string
    type: 'authorized' | 'suggestion'
}

const defaultValue = 'https://'

export const appUrlsLogic = kea<appUrlsLogicType<KeyedAppUrl>>({
    path: ['lib', 'components', 'AppEditorLink', 'appUrlsLogic'],
    props: {} as {
        actionId?: number
    },
    connect: {
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
    },
    actions: () => ({
        setAppUrls: (appUrls: string[]) => ({ appUrls }),
        addUrl: (value: string) => ({ value }),
        addUrlAndGo: (value: string) => ({ value }),
        removeUrl: (index: number) => ({ index }),
        updateUrl: (index: number, value: string) => ({ index, value }),
        launchAtUrl: (url: string) => ({ url }),
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
                addUrl: (state, { value }) => state.concat([value || defaultValue]),
                updateUrl: (state, { index, value }) => Object.assign([...state], { [index]: value }),
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
                addUrl: (state, { value }) => [...state].filter((item) => value !== item),
            },
        ],
    }),
    listeners: ({ values, sharedListeners, props, actions }) => ({
        addUrlAndGo: async ({ value }) => {
            // TODO: Need to refactor this to use `teamLogic.actions.updateCurrentTeam`
            const app_urls = [...values.appUrls, value]
            await api.update('api/projects/@current', { app_urls })
            actions.launchAtUrl(value)
        },
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
            (s) => [s.appUrls, s.suggestions],
            (appUrls, suggestions): KeyedAppUrl[] =>
                appUrls
                    .map((url) => ({
                        url,
                        type: 'authorized',
                    }))
                    .concat(
                        suggestions.map((url) => ({
                            url,
                            type: 'suggestion',
                        }))
                    ) as KeyedAppUrl[],
        ],
    },
})
