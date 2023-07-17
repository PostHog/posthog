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
import { ToolbarParams, TrendResult } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs } from 'lib/dayjs'
import Fuse from 'fuse.js'
import { encodeParams, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

import type { authorizedUrlListLogicType } from './authorizedUrlListLogicType'
import { subscriptions } from 'kea-subscriptions'

export interface ProposeNewUrlFormType {
    url: string
}

export enum AuthorizedUrlListType {
    TOOLBAR_URLS = 'TOOLBAR_URLS',
    RECORDING_DOMAINS = 'RECORDING_DOMAINS',
}

export const validateProposedUrl = (
    proposedUrl: string,
    currentUrls: string[],
    onlyAllowDomains: boolean = false
): string | undefined => {
    if (!onlyAllowDomains && !isURL(proposedUrl)) {
        return 'Please enter a valid URL'
    }

    if (onlyAllowDomains && !isDomain(proposedUrl)) {
        return "Please enter a valid domain (URLs with a path aren't allowed)"
    }

    if (proposedUrl.indexOf('*') > -1 && !proposedUrl.match(/^(.*)\*[^*]*\.[^*]+\.[^*]+$/)) {
        return 'Wildcards can only be used for subdomains'
    }

    if (currentUrls.indexOf(proposedUrl) > -1) {
        return `This ${onlyAllowDomains ? 'domains' : 'URL'} already is registered`
    }

    return
}

/** defaultIntent: whether to launch with empty intent (i.e. toolbar mode is default) */
export function appEditorUrl(appUrl: string, actionId?: number | null, defaultIntent?: boolean): string {
    // See https://github.com/PostHog/posthog-js/blob/f7119c/src/extensions/toolbar.ts#L52 for where these params
    // are passed. `appUrl` is an extra `redirect_to_site` param.
    const params: ToolbarParams & { appUrl: string } = {
        userIntent: defaultIntent ? undefined : actionId ? 'edit-action' : 'add-action',
        // Make sure to pass the app url, otherwise the api_host will be used by
        // the toolbar, which isn't correct when used behind a reverse proxy as
        // we require e.g. SSO login to the app, which will not work when placed
        // behind a proxy unless we register each domain with the OAuth2 client.
        apiURL: window.location.origin,
        appUrl,
        ...(actionId ? { actionId } : {}),
    }
    return '/api/user/redirect_to_site/' + encodeParams(params, '?')
}

export const NEW_URL = 'https://'

export interface KeyedAppUrl {
    url: string
    type: 'authorized' | 'suggestion'
    originalIndex: number
}

export interface AuthorizedUrlListLogicProps {
    actionId: number | null
    type: AuthorizedUrlListType
}
export const authorizedUrlListLogic = kea<authorizedUrlListLogicType>([
    path((key) => ['lib', 'components', 'AuthorizedUrlList', 'authorizedUrlListLogic', key]),
    key((props) => `${props.type}-${props.actionId}`),
    props({} as AuthorizedUrlListLogicProps),
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
    subscriptions(({ props, actions }) => ({
        currentTeam: (currentTeam) => {
            actions.setAuthorizedUrls(
                (props.type === AuthorizedUrlListType.RECORDING_DOMAINS
                    ? currentTeam.recording_domains
                    : currentTeam.app_urls) || []
            )
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSuggestions()
    }),
    forms(({ values, actions }) => ({
        proposedUrl: {
            defaults: { url: '' } as ProposeNewUrlFormType,
            errors: ({ url }) => ({
                url: validateProposedUrl(url, values.authorizedUrls, values.onlyAllowDomains),
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
        saveUrls: async () => {
            if (props.type === AuthorizedUrlListType.RECORDING_DOMAINS) {
                await teamLogic.asyncActions.updateCurrentTeam({ recording_domains: values.authorizedUrls })
            } else {
                await teamLogic.asyncActions.updateCurrentTeam({ app_urls: values.authorizedUrls })
            }
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
            sharedListeners.saveUrls,
            ({ url, launch }) => {
                if (launch) {
                    actions.launchAtUrl(url)
                }
            },
        ],
        removeUrl: sharedListeners.saveUrls,
        updateUrl: sharedListeners.saveUrls,
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
    selectors({
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
        launchUrl: [(_, p) => [p.actionId], (actionId) => (url: string) => appEditorUrl(url, actionId, !actionId)],
        isAddUrlFormVisible: [(s) => [s.editUrlIndex], (editUrlIndex) => editUrlIndex === -1],
        onlyAllowDomains: [(_, p) => [p.type], (type) => type === AuthorizedUrlListType.RECORDING_DOMAINS],
    }),
    urlToAction(({ actions }) => ({
        [urls.toolbarLaunch()]: (_, searchParams) => {
            if (searchParams.addNew) {
                actions.newUrl()
            }
        },
    })),
])
