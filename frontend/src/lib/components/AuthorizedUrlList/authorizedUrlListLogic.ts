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
import { isDomain, isURL, toParams } from 'lib/utils'
import { EditorProps, TrendResult } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs } from 'lib/dayjs'
import Fuse from 'fuse.js'
import { encodeParams, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

import type { authorizedUrlListLogicType } from './authorizedUrlListLogicType'

export interface ProposeNewUrlFormType {
    url: string
}

export enum AuthorizedUrlListType {
    TOOLBAR_URLS = 'TOOLBAR_URLS',
    RECORDING_DOMAINS = 'RECORDING_DOMAINS',
}

export const validateProposedURL = (
    proposedUrl: string,
    currentUrls: string[],
    onlyAllowDomains: boolean
): string | undefined => {
    if (proposedUrl === '') {
        return 'Please type a valid URL or domain.'
    }

    if (proposedUrl.indexOf('*') > -1 && !proposedUrl.match(/^(.*)\*[^*]*\.[^*]+\.[^*]+$/)) {
        return 'You can only wildcard subdomains. If you wildcard the domain or TLD, people might be able to gain access to your PostHog data.'
    }

    if (!onlyAllowDomains && !isURL(proposedUrl)) {
        return 'Please type a valid URL or domain.'
    }

    if (onlyAllowDomains && !isDomain(proposedUrl)) {
        return "Please type a valid domain (URLs with a path aren't allowed)."
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

export interface AuthorizedUrlListProps {
    actionId?: number
    pageKey?: string
    type: AuthorizedUrlListType
}
export const authorizedUrlListLogic = kea<authorizedUrlListLogicType>([
    path((key) => ['lib', 'components', 'AuthorizedUrlList', 'authorizedUrlListLogic', key]),
    key((props) => `${props.pageKey}-${props.type}-${props.actionId}`),
    props({} as AuthorizedUrlListProps),
    connect({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions(() => ({
        setAuthorizedUrls: (authorizedUrls: string[]) => ({ authorizedUrls }),
        addUrl: (url: string, launch?: boolean) => ({ url, launch }),
        newUrl: true,
        removeUrl: (index: number) => ({ index }),
        updateUrl: (index: number, url: string) => ({ index, url }),
        launchAtUrl: (url: string) => ({ url }),
        setSearchTerm: (term: string) => ({ term }),
        setEditUrlIndex: (originalIndex: number | null) => ({ originalIndex }),
        cancelProposingUrl: true,
    })),
    loaders(({ values, props }) => ({
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
                const suggestedDomains: string[] = []

                result.forEach((item) => {
                    if (item.breakdown_value && typeof item.breakdown_value === 'string') {
                        try {
                            const parsedUrl = new URL(item.breakdown_value)
                            const urlWithoutPath = parsedUrl.protocol + '//' + parsedUrl.host
                            // Have we already added this domain?
                            if (suggestedDomains.indexOf(urlWithoutPath) > -1) {
                                return
                            }
                            // Is this domain already in the list of urls?
                            const existingUrls =
                                props.type === AuthorizedUrlListType.RECORDING_DOMAINS
                                    ? values.currentTeam?.recording_domains
                                    : values.currentTeam?.app_urls
                            if (
                                existingUrls &&
                                existingUrls.filter((url) => url.indexOf(urlWithoutPath) > -1).length > 0
                            ) {
                                return
                            }
                            suggestedDomains.push(urlWithoutPath)
                        } catch (error) {
                            return
                        }
                    }
                })

                return suggestedDomains.slice(0, 20)
            },
        },
    })),
    afterMount(({ actions, values, props }) => {
        actions.loadSuggestions()
        if (values.currentTeam) {
            actions.setAuthorizedUrls(
                (props.type === AuthorizedUrlListType.RECORDING_DOMAINS
                    ? values.currentTeam.recording_domains
                    : values.currentTeam.app_urls) || []
            )
        }
    }),
    forms(({ values, actions }) => ({
        proposedUrl: {
            defaults: { url: '' } as ProposeNewUrlFormType,
            errors: ({ url }) => ({
                url: validateProposedURL(url, values.authorizedUrls, values.onlyAllowDomains),
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
        authorizedUrls: [
            [] as string[],
            {
                setAuthorizedUrls: (_, { authorizedUrls }) => authorizedUrls,
                addUrl: (state, { url }) => state.concat([url]),
                updateUrl: (state, { index, url }) => Object.assign([...state], { [index]: url }),
                removeUrl: (state, { index }) => {
                    const newUrls = [...state]
                    newUrls.splice(index, 1)
                    return newUrls
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
    sharedListeners(({ values, props }) => ({
        saveUrls: () => {
            if (props.type === AuthorizedUrlListType.RECORDING_DOMAINS) {
                teamLogic.actions.updateCurrentTeam({ recording_domains: values.authorizedUrls })
            } else {
                teamLogic.actions.updateCurrentTeam({ app_urls: values.authorizedUrls })
            }
        },
    })),
    listeners(({ sharedListeners, values, actions, props }) => ({
        setEditUrlIndex: () => {
            actions.setProposedUrlValue('url', values.urlToEdit)
        },
        newUrl: () => {
            actions.setProposedUrlValue('url', NEW_URL)
        },
        addUrl: [
            sharedListeners.saveUrls,
            async ({ url, launch }) => {
                if (launch) {
                    actions.launchAtUrl(url)
                }
            },
        ],
        removeUrl: sharedListeners.saveUrls,
        updateUrl: sharedListeners.saveUrls,
        [teamLogic.actionTypes.loadCurrentTeamSuccess]: async ({ currentTeam }) => {
            if (currentTeam) {
                actions.setAuthorizedUrls(
                    props.type === AuthorizedUrlListType.RECORDING_DOMAINS
                        ? currentTeam.recording_domains
                        : currentTeam.app_urls
                )
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
            (s) => [s.authorizedUrls, s.editUrlIndex],
            (authorizedUrls, editUrlIndex) => {
                if (editUrlIndex === null || editUrlIndex === -1) {
                    return NEW_URL
                }
                return authorizedUrls[editUrlIndex]
            },
        ],
        urlsKeyed: [
            (s) => [s.authorizedUrls, s.suggestions, s.searchTerm],
            (authorizedUrls, suggestions, searchTerm): KeyedAppUrl[] => {
                const keyedUrls = authorizedUrls
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
                    return keyedUrls
                }

                return new Fuse(keyedUrls, {
                    keys: ['url'],
                    threshold: 0.3,
                })
                    .search(searchTerm)
                    .map((result) => result.item)
            },
        ],
        launchUrl: [() => [], () => (url: string) => appEditorUrl(url, props.actionId, !props.actionId)],
        isAddUrlFormVisible: [(s) => [s.editUrlIndex], (editUrlIndex) => editUrlIndex === -1],
        onlyAllowDomains: [() => [], () => props.type === AuthorizedUrlListType.RECORDING_DOMAINS],
    })),
    urlToAction(({ actions }) => ({
        [urls.toolbarLaunch()]: (_, searchParams) => {
            if (searchParams.addNew) {
                actions.newUrl()
            }
        },
    })),
])
