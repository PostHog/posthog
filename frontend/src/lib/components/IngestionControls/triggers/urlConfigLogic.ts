import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { UrlTriggerConfig } from 'lib/components/IngestionControls/types'

import type { urlConfigLogicType } from './urlConfigLogicType'

const NEW_URL_TRIGGER = { url: '', matching: 'regex' }

export function isStringWithLength(x: unknown): x is string {
    return typeof x === 'string' && x.trim() !== ''
}

function ensureAnchored(url: string): string {
    url = url.startsWith('^') ? url.substring(1) : url
    url = url.endsWith('$') ? url.substring(0, url.length - 1) : url
    return `^${url}$`
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
                validateUrlInput: (_, { url, type }) => {
                    if (type !== 'trigger') {
                        return _
                    }
                    // Check if it ends with a TLD
                    if (/\.[a-z]{2,}\/?$/i.test(url)) {
                        const sanitizedUrl = url.endsWith('/') ? url.slice(0, -1) : url
                        return `If you want to match all paths of a domain, you should write " ${sanitizedUrl}(/.*)? ". This would match: 
                        ${sanitizedUrl}, ${sanitizedUrl}/, ${sanitizedUrl}/page, etc. Don't forget to include https:// at the beginning of the url.`
                    }
                    return null
                },
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
