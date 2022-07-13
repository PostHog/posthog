import {
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
    sharedListeners,
} from 'kea'
import api from 'lib/api'
import { isURL, toParams } from 'lib/utils'
import { EditorProps, TrendResult } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs } from 'lib/dayjs'
import Fuse from 'fuse.js'
import type { authorizedUrlsLogicType } from './authorizedUrlsLogicType'
import { encodeParams, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

export interface ProposeNewUrlFormType {
    url: string
}

export const validateProposedURL = (proposedUrl: string, currentUrls: string[]): string | undefined => {
    if (proposedUrl === '') {
        return 'Please type a valid URL or domain.'
    }

    if (proposedUrl.indexOf('*') > -1 && !proposedUrl.match(/^(.*)\*[^*]*\.[^*]+\.[^*]+$/)) {
        return 'You can only wildcard subdomains. If you wildcard the domain or TLD, people might be able to gain access to your PostHog data.'
    }

    if (!isURL(proposedUrl)) {
        return 'Please type a valid URL or domain.'
    }

    if (currentUrls.indexOf(proposedUrl) > -1) {
        return 'This URL is already registered.'
    }

    return
}

/** defaultIntent: whether to launch with empty intent (i.e. toolbar mode is default) */
export function appEditorUrl(appUrl?: string, actionId?: number, defaultIntent?: boolean): string {
    const params: EditorProps = {
        userIntent: defaultIntent ? undefined : actionId ? 'edit-action' : 'add-action',
        ...(actionId ? { actionId } : {}),
        ...(appUrl ? { appUrl } : {}),
    }
    return '/api/user/redirect_to_site/' + encodeParams(params, '?')
}

export const NEW_URL = 'https://'

export interface KeyedAppUrl {
    url: string
    type: 'authorized' | 'suggestion'
    originalIndex: number
}

export const authorizedUrlsLogic = kea<authorizedUrlsLogicType>([
    path((key) => ['lib', 'components', 'AppEditorLink', 'appUrlsLogic', key]),
    key((props) => `${props.pageKey}${props.actionId}` || 'global'),
    props(
        {} as {
            actionId?: number
            pageKey?: string
        }
    ),
    connect({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions(() => ({
        setAppUrls: (appUrls: string[]) => ({ appUrls }),
        addUrl: (url: string, launch?: boolean) => ({ url, launch }),
        newUrl: true,
        removeUrl: (index: number) => ({ index }),
        updateUrl: (index: number, url: string) => ({ index, url }),
        launchAtUrl: (url: string) => ({ url }),
        setSearchTerm: (term: string) => ({ term }),
        setEditUrlIndex: (originalIndex: number | null) => ({ originalIndex }),
        cancelProposingUrl: true,
    })),
    loaders(({ values }) => ({
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
    })),
    afterMount(({ actions, values }) => {
        actions.loadSuggestions()
        if (values.currentTeam) {
            actions.setAppUrls(values.currentTeam.app_urls)
        }
    }),
    forms(({ values, actions }) => ({
        proposedUrl: {
            defaults: { url: '' } as ProposeNewUrlFormType,
            errors: ({ url }) => ({
                url: validateProposedURL(url, values.appUrls),
            }),
            submit: async ({ url }) => {
                if (values.editUrlIndex !== null && values.editUrlIndex >= 0) {
                    actions.updateUrl(values.editUrlIndex, url)
                } else {
                    actions.addUrl(url)
                }
            },
        },
    })),
    reducers(() => ({
        showProposedURLForm: [
            false as boolean,
            {
                newUrl: () => true,
                submitProposedUrlSuccess: () => false,
                cancelProposingUrl: () => false,
            },
        ],
        appUrls: [
            [] as string[],
            {
                setAppUrls: (_, { appUrls }) => appUrls,
                addUrl: (state, { url }) => state.concat([url]),
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
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
            },
        ],
        editUrlIndex: [
            null as number | null,
            {
                setEditUrlIndex: (_, { originalIndex }) => originalIndex,
                removeUrl: (editUrlIndex, { index }) =>
                    editUrlIndex && index < editUrlIndex
                        ? editUrlIndex - 1
                        : index === editUrlIndex
                        ? null
                        : editUrlIndex,
                newUrl: () => -1,
                updateUrl: () => null,
                addUrl: () => null,
                cancelProposingUrl: () => null,
            },
        ],
    })),
    sharedListeners(({ values }) => ({
        saveAppUrls: () => {
            teamLogic.actions.updateCurrentTeam({ app_urls: values.appUrls })
        },
    })),
    listeners(({ sharedListeners, values, actions }) => ({
        setEditUrlIndex: () => {
            actions.setProposedUrlValue('url', values.urlToEdit)
        },
        newUrl: () => {
            actions.setProposedUrlValue('url', NEW_URL)
        },
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
            window.location.href = values.launchUrl(url)
        },
        cancelProposingUrl: () => {
            actions.resetProposedUrl()
        },
        submitProposedUrlSuccess: () => {
            actions.setEditUrlIndex(null)
            actions.resetProposedUrl()
        },
    })),
    selectors(({ props }) => ({
        urlToEdit: [
            (s) => [s.appUrls, s.editUrlIndex],
            (appUrls, editUrlIndex) => {
                if (editUrlIndex === null || editUrlIndex === -1) {
                    return NEW_URL
                }
                return appUrls[editUrlIndex]
            },
        ],
        appUrlsKeyed: [
            (s) => [s.appUrls, s.suggestions, s.searchTerm],
            (appUrls, suggestions, searchTerm): KeyedAppUrl[] => {
                const urls = appUrls
                    .map((url, index) => ({
                        url,
                        type: 'authorized',
                        originalIndex: index,
                    }))
                    .concat(
                        suggestions.map((url, index) => ({
                            url,
                            type: 'suggestion',
                            originalIndex: index,
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
        launchUrl: [() => [], () => (url: string) => appEditorUrl(url, props.actionId, !props.actionId)],
        isAddUrlFormVisible: [(s) => [s.editUrlIndex], (editUrlIndex) => editUrlIndex === -1],
    })),
    urlToAction(({ actions }) => ({
        [urls.toolbarLaunch()]: (_, searchParams) => {
            if (searchParams.addNew) {
                actions.newUrl()
            }
        },
    })),
])
