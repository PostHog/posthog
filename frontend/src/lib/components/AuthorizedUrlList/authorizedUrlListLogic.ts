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
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { encodeParams, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { isDomain, isURL } from 'lib/utils'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { ExperimentIdType, ToolbarParams, ToolbarUserIntent } from '~/types'

import type { authorizedUrlListLogicType } from './authorizedUrlListLogicType'

export interface ProposeNewUrlFormType {
    url: string
}

export enum AuthorizedUrlListType {
    TOOLBAR_URLS = 'TOOLBAR_URLS',
    RECORDING_DOMAINS = 'RECORDING_DOMAINS',
    WEB_ANALYTICS = 'WEB_ANALYTICS',
    WEB_EXPERIMENTS = 'WEB_EXPERIMENTS',
}

/**
 * Firefox does not allow you construct a new URL with e.g. https://*.example.com (which is to be fair more standards compliant than Chrome)
 * when used to probe for e.g. for authorized urls we only care if the proposed URL has a path so we can safely replace the wildcard with a character
 */
export function sanitizePossibleWildCardedURL(url: string): URL {
    const deWildCardedURL = url.replace(/\*/g, 'x')
    return new URL(deWildCardedURL)
}

/**
 * Checks if the URL has a wildcard (*) in the port position e.g. http://localhost:*
 */
export function hasWildcardInPort(input: unknown): boolean {
    if (!input || typeof input !== 'string') {
        return false
    }
    // This regex matches URLs with a wildcard (*) in the port position
    const portWildcardRegex = /^(https?:\/\/[^:/]+):\*(.*)$/
    return portWildcardRegex.test(input.trim())
}

export const validateProposedUrl = (
    proposedUrl: string,
    currentUrls: string[],
    onlyAllowDomains: boolean = false,
    allowWildCards: boolean = true
): string | undefined => {
    if (!isURL(proposedUrl)) {
        return 'Please enter a valid URL'
    }

    if (hasWildcardInPort(proposedUrl)) {
        return 'Wildcards are not allowed in the port position'
    }

    if (onlyAllowDomains && !isDomain(sanitizePossibleWildCardedURL(proposedUrl))) {
        return "Please enter a valid domain (URLs with a path aren't allowed)"
    }

    const hasWildCard = proposedUrl.indexOf('*') > -1
    if (hasWildCard && allowWildCards === false) {
        return 'Wildcards are not allowed'
    }

    if (
        hasWildCard &&
        !/^https?:\/\/((\*\.)?localhost|localhost)(:\d+)?$/.test(proposedUrl) && // Allow http://*.localhost and localhost with ports
        !proposedUrl.match(/^(.*)\*[^*]*\.[^*]+\.[^*]+$/)
    ) {
        return 'Wildcards can only be used for subdomains'
    }

    if (currentUrls.indexOf(proposedUrl) > -1) {
        return `This ${onlyAllowDomains ? 'domains' : 'URL'} already is registered`
    }

    return
}

function buildToolbarParams(options?: {
    actionId?: number | null
    experimentId?: ExperimentIdType
    userIntent?: ToolbarUserIntent
}): ToolbarParams {
    return {
        userIntent:
            options?.userIntent ??
            (options?.actionId ? 'edit-action' : options?.experimentId ? 'edit-experiment' : 'add-action'),
        // Make sure to pass the app url, otherwise the api_host will be used by
        // the toolbar, which isn't correct when used behind a reverse proxy as
        // we require e.g. SSO login to the app, which will not work when placed
        // behind a proxy unless we register each domain with the OAuth2 client.
        apiURL: apiHostOrigin(),
        ...(options?.actionId ? { actionId: options.actionId } : {}),
        ...(options?.experimentId ? { experimentId: options.experimentId } : {}),
    }
}

/** defaultIntent: whether to launch with empty intent (i.e. toolbar mode is default) */
export function appEditorUrl(
    appUrl: string,
    options?: {
        actionId?: number | null
        experimentId?: ExperimentIdType
        userIntent?: ToolbarUserIntent
        generateOnly?: boolean
    }
): string {
    const params = buildToolbarParams(options) as Record<string, unknown>
    // See https://github.com/PostHog/posthog-js/blob/f7119c/src/extensions/toolbar.ts#L52 for where these params
    // are passed. `appUrl` is an extra `redirect_to_site` param.
    params['appUrl'] = appUrl
    params['generateOnly'] = options?.generateOnly
    return '/api/user/redirect_to_site/' + encodeParams(params, '?')
}

export const checkUrlIsAuthorized = (url: string | URL, authorizedUrls: string[]): boolean => {
    try {
        const parsedUrl = typeof url === 'string' ? sanitizePossibleWildCardedURL(url) : url
        const urlWithoutPath = parsedUrl.protocol + '//' + parsedUrl.host
        // Is this domain already in the list of urls?
        const exactMatch =
            authorizedUrls.filter((authorizedUrl) => authorizedUrl.indexOf(urlWithoutPath) > -1).length > 0

        if (exactMatch) {
            return true
        }

        const wildcardMatch = !!authorizedUrls.find((authorizedUrl) => {
            // Matches something like `https://*.example.com` against the urlWithoutPath
            const regex = new RegExp(authorizedUrl.replace(/\./g, '\\.').replace(/\*/g, '.*'))
            return urlWithoutPath.match(regex)
        })

        if (wildcardMatch) {
            return true
        }
    } catch {
        // Ignore invalid URLs
    }

    return false
}

export interface SuggestedDomain {
    url: string
    count: number
}

export const filterNotAuthorizedUrls = (
    suggestions: SuggestedDomain[],
    authorizedUrls: string[]
): SuggestedDomain[] => {
    const suggestedDomains: SuggestedDomain[] = []

    suggestions.forEach(({ url, count }) => {
        const parsedUrl = sanitizePossibleWildCardedURL(url)
        const urlWithoutPath = parsedUrl.protocol + '//' + parsedUrl.host
        // Have we already added this domain?
        if (suggestedDomains.some((sd) => sd.url === urlWithoutPath)) {
            return
        }

        if (!checkUrlIsAuthorized(parsedUrl, authorizedUrls)) {
            suggestedDomains.push({ url: urlWithoutPath, count })
        }
    })

    return suggestedDomains
}

export const NEW_URL = 'https://'

export interface KeyedAppUrl {
    url: string
    type: 'authorized' | 'suggestion'
    originalIndex: number
    // how many seen in the last three days
    count?: number
}

export interface AuthorizedUrlListLogicProps {
    actionId: number | null
    experimentId: ExperimentIdType | null
    type: AuthorizedUrlListType
    allowWildCards?: boolean
}

export const defaultAuthorizedUrlProperties = {
    actionId: null,
    experimentId: null,
}

export const authorizedUrlListLogic = kea<authorizedUrlListLogicType>([
    path((key) => ['lib', 'components', 'AuthorizedUrlList', 'authorizedUrlListLogic', key]),
    key((props) => `${props.type}-${props.experimentId}-${props.actionId}`), // Some will be undefined but that's ok, this avoids experiment/action with same ID sharing same store
    props({} as AuthorizedUrlListLogicProps),
    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    actions(() => ({
        setAuthorizedUrls: (authorizedUrls: string[]) => ({ authorizedUrls }),
        addUrl: (url: string, launch?: boolean) => ({ url, launch }),
        newUrl: true,
        removeUrl: (index: number) => ({ index }),
        updateUrl: (index: number, url: string) => ({ index, url }),
        launchAtUrl: (url: string) => ({ url }),
        setEditUrlIndex: (originalIndex: number | null) => ({ originalIndex }),
        cancelProposingUrl: true,
        copyLaunchCode: (url: string) => ({ url }),
    })),
    loaders(({ values, props }) => ({
        suggestions: {
            __default: [] as SuggestedDomain[],
            loadSuggestions: async () => {
                const query = hogql`
                    select properties.$current_url, count()
                    from events
                        where event = '$pageview'
                        and timestamp >= now() - interval 3 day 
                        and timestamp <= now()
                        and properties.$current_url is not null
                        group by properties.$current_url
                        order by count() desc
                    limit 25`

                const response = await api.queryHogQL(query)
                const result = response.results as [string, number][]

                if (result && result.length === 0) {
                    return []
                }

                const suggestedDomains = filterNotAuthorizedUrls(
                    result.map(([url, count]) => ({ url, count })),
                    values.authorizedUrls
                )

                return suggestedDomains.slice(0, 20)
            },
        },
        manualLaunchParams: {
            loadManualLaunchParams: async (url: string): Promise<string | undefined> => {
                const response = await api.get(
                    appEditorUrl(url, {
                        ...(props?.actionId ? { actionId: props.actionId } : {}),
                        ...(props?.experimentId ? { experimentId: props.experimentId } : {}),
                        generateOnly: true,
                    })
                )

                let decoded: string | undefined = undefined
                try {
                    if (response?.toolbarParams) {
                        decoded = decodeURIComponent(response.toolbarParams)
                    }
                } catch {
                    lemonToast.error('Failed to generate toolbar params')
                }
                return decoded
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
    forms(({ values, actions, props }) => ({
        proposedUrl: {
            defaults: { url: '' } as ProposeNewUrlFormType,
            errors: ({ url }) => ({
                // default to allowing wildcards because that was the original behavior
                url: validateProposedUrl(
                    url,
                    values.authorizedUrls,
                    values.onlyAllowDomains,
                    props.allowWildCards ?? true
                ),
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
                addUrl: (state, { url }) => (!state.includes(url) ? state.concat([url]) : state),
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
                addUrl: (state, { url }) => [...state].filter((sd) => url !== sd.url),
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
        copyLaunchCode: ({ url }) => {
            actions.loadManualLaunchParams(url)
        },
        loadManualLaunchParamsSuccess: async ({ manualLaunchParams }) => {
            if (manualLaunchParams) {
                const templateScript = `
                if (!window?.posthog) {
                    console.warn('PostHog must be added to the window object on this page, for this to work. This is normally done in the loaded callback of your posthog init code.')
                } else {
                    window.posthog.loadToolbar(${manualLaunchParams})
                }
                `
                await copyToClipboard(templateScript, 'code to paste into the console')
            }
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
            (s) => [s.authorizedUrls, s.suggestions],
            (authorizedUrls, suggestions): KeyedAppUrl[] => {
                const keyedUrls = authorizedUrls
                    .map((url, index) => ({
                        url,
                        type: 'authorized',
                        originalIndex: index,
                    }))
                    .concat(
                        suggestions.map(({ url, count }, index) => ({
                            url,
                            type: 'suggestion',
                            originalIndex: index,
                            count,
                        }))
                    ) as KeyedAppUrl[]

                return keyedUrls
            },
        ],
        launchUrl: [
            (_, p) => [p.actionId, p.experimentId],
            (actionId, experimentId) => (url: string) => {
                if (experimentId) {
                    return appEditorUrl(url, {
                        experimentId,
                    })
                }

                return appEditorUrl(url, {
                    actionId,
                })
            },
        ],
        isAddUrlFormVisible: [(s) => [s.editUrlIndex], (editUrlIndex) => editUrlIndex === -1],
        onlyAllowDomains: [(_, p) => [p.type], (type) => type === AuthorizedUrlListType.RECORDING_DOMAINS],

        checkUrlIsAuthorized: [
            (s) => [s.authorizedUrls],
            (authorizedUrls) => (url: string) => {
                return checkUrlIsAuthorized(url, authorizedUrls)
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        [urls.toolbarLaunch()]: (_, searchParams) => {
            if (searchParams.addNew) {
                actions.newUrl()
            }
        },
    })),
])
