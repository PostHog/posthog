import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { UrlTriggerConfig } from 'lib/components/IngestionControls/types'

import type { urlConfigLogicType } from './urlConfigLogicType'

const NEW_URL_TRIGGER = { url: '', matching: 'regex' }

export function isStringWithLength(x: unknown): x is string {
    return typeof x === 'string' && x.trim() !== ''
}

export function ensureAnchored(url: string): string {
    url = url.startsWith('^') ? url.substring(1) : url
    url = url.endsWith('$') ? url.substring(0, url.length - 1) : url
    return `^${url}$`
}

const BARE_HOSTNAME_ONLY_REGEX = /^\^?[a-zA-Z0-9.-]+\.[a-z]{2,}\/?\$?$/i

/**
 * Detects when a stored/raw regex pattern is a bare hostname ending in a TLD —
 * e.g. `www.example.com`, `^www.example.com$`. Once anchored with `^...$` these
 * patterns can never match a URL produced by `window.location.href` (which always
 * includes a protocol prefix and typically a path), so they fail silently —
 * notably for blocklists this means recordings are captured on domains the user
 * explicitly tried to exclude. We surface this as a warning in the UI.
 */
export function isLikelyUnmatchableUrlPattern(pattern: string): boolean {
    if (!pattern) {
        return false
    }
    return BARE_HOSTNAME_ONLY_REGEX.test(pattern.trim())
}

export function urlPatternMatchWarning(url: string): string | null {
    if (!url) {
        return null
    }
    if (/\.[a-z]{2,}\/?$/i.test(url)) {
        const sanitizedUrl = url.endsWith('/') ? url.slice(0, -1) : url
        return `If you want to match all paths of a domain, include the protocol and path wildcard — e.g. "https?://${sanitizedUrl}(/.*)?". As written, "${sanitizedUrl}" will be stored as the regex "^${sanitizedUrl}$" which cannot match a real page URL.`
    }
    return null
}

export interface UrlConfigLogicProps {
    logicKey: string
    initialUrlTriggerConfig: UrlTriggerConfig[]
    onChange: (urlTriggerConfig: UrlTriggerConfig[]) => void
}

export const urlConfigLogic = kea<urlConfigLogicType>([
    props({} as UrlConfigLogicProps),
    key((props) => props.logicKey),
    path((key) => ['lib', 'components', 'IngestionControls', 'triggers', 'urlConfigLogic', key]),
    actions({
        setUrlTriggerConfig: (urlTriggerConfig: UrlTriggerConfig[]) => ({ urlTriggerConfig }),
        addUrlTrigger: (urlTriggerConfig: UrlTriggerConfig) => ({ urlTriggerConfig }),
        removeUrlTrigger: (index: number) => ({ index }),
        updateUrlTrigger: (index: number, urlTriggerConfig: UrlTriggerConfig) => ({
            index,
            urlTriggerConfig,
        }),
        setEditUrlTriggerIndex: (originalIndex: number | null) => ({ originalIndex }),
        newUrlTrigger: true,
        cancelProposingUrlTrigger: true,

        setCheckUrlTrigger: (url: string) => ({ url }),
        setCheckUrlBlocklist: (url: string) => ({ url }),
        validateUrlInput: (url: string, type: 'trigger' | 'blocklist') => ({ url, type }),
    }),
    reducers(({ props }) => ({
        urlTriggerConfig: [
            props.initialUrlTriggerConfig as UrlTriggerConfig[],
            {
                setUrlTriggerConfig: (_, { urlTriggerConfig }) => urlTriggerConfig,
                addUrlTrigger: (state, { urlTriggerConfig }) => [...(state ?? []), urlTriggerConfig],
                updateUrlTrigger: (state, { index, urlTriggerConfig: newUrlTriggerConfig }) =>
                    (state ?? []).map((triggerConfig, i) => (i === index ? newUrlTriggerConfig : triggerConfig)),
                removeUrlTrigger: (state, { index }) => {
                    return (state ?? []).filter((_, i) => i !== index)
                },
            },
        ],
        editUrlTriggerIndex: [
            null as number | null,
            {
                setEditUrlTriggerIndex: (_, { originalIndex }) => originalIndex,
                removeUrlTrigger: (editUrlTriggerIndex, { index }) =>
                    editUrlTriggerIndex !== null && index < editUrlTriggerIndex
                        ? editUrlTriggerIndex - 1
                        : index === editUrlTriggerIndex
                          ? null
                          : editUrlTriggerIndex,
                newUrlTrigger: () => -1,
                updateUrlTrigger: () => null,
                addUrlTrigger: () => null,
                cancelProposingUrlTrigger: () => null,
            },
        ],
        checkUrlTrigger: [
            '' as string,
            {
                setCheckUrlTrigger: (_, { url }) => url,
            },
        ],
        urlTriggerInputValidationWarning: [
            null as string | null,
            {
                validateUrlInput: (_, { url }) => urlPatternMatchWarning(url),
            },
        ],
    })),
    selectors({
        isAddUrlTriggerConfigFormVisible: [
            (s) => [s.editUrlTriggerIndex],
            (editUrlTriggerIndex) => editUrlTriggerIndex === -1,
        ],
        urlTriggerToEdit: [
            (s) => [s.urlTriggerConfig, s.editUrlTriggerIndex],
            (urlTriggerConfig, editUrlTriggerIndex) => {
                if (
                    editUrlTriggerIndex === null ||
                    editUrlTriggerIndex === -1 ||
                    !urlTriggerConfig?.[editUrlTriggerIndex]
                ) {
                    return NEW_URL_TRIGGER
                }
                return urlTriggerConfig[editUrlTriggerIndex]
            },
        ],

        checkUrlTriggerResults: [
            (s) => [s.checkUrlTrigger, s.urlTriggerConfig],
            (checkUrl, urlTriggerConfig): { [key: number]: boolean } => {
                if (!checkUrl.trim() || !urlTriggerConfig) {
                    return {}
                }

                const results: { [key: number]: boolean } = {}
                urlTriggerConfig.forEach((trigger, index) => {
                    try {
                        const regex = new RegExp(trigger.url)
                        results[index] = regex.test(checkUrl)
                    } catch {
                        results[index] = false
                    }
                })
                return results
            },
        ],
    }),
    forms(({ values, actions }) => ({
        proposedUrlTrigger: {
            defaults: { url: '', matching: 'regex' } as UrlTriggerConfig,
            errors: ({ url }) => ({
                url: !url
                    ? 'Must have a URL'
                    : (() => {
                          try {
                              new RegExp(url)
                              return undefined
                          } catch {
                              return 'Invalid regex pattern'
                          }
                      })(),
            }),
            submit: async ({ url, matching }) => {
                if (values.editUrlTriggerIndex !== null && values.editUrlTriggerIndex >= 0) {
                    actions.updateUrlTrigger(values.editUrlTriggerIndex, { url: ensureAnchored(url), matching })
                } else {
                    actions.addUrlTrigger({ url: ensureAnchored(url), matching })
                }
            },
        },
    })),
    listeners(({ actions, values, props }) => ({
        setEditUrlTriggerIndex: () => {
            actions.setProposedUrlTriggerValue('url', values.urlTriggerToEdit.url)
            actions.setProposedUrlTriggerValue('matching', values.urlTriggerToEdit.matching)
        },
        addUrlTrigger: () => props.onChange(values.urlTriggerConfig),
        removeUrlTrigger: () => props.onChange(values.urlTriggerConfig),
        updateUrlTrigger: () => props.onChange(values.urlTriggerConfig),
        submitProposedUrlTriggerSuccess: () => {
            actions.setEditUrlTriggerIndex(null)
            actions.resetProposedUrlTrigger()
        },
        setProposedUrlTriggerValue: ({ name, value }) => {
            const fieldName = Array.isArray(name) ? name[0] : name
            if (fieldName === 'url') {
                actions.validateUrlInput(value || '', 'trigger')
            }
        },
    })),
])
