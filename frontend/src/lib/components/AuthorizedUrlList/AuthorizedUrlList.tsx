import { IconCopy, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconOpenInApp, IconRefresh } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useMemo } from 'react'

import { ExperimentIdType } from '~/types'

import { authorizedUrlListLogic, AuthorizedUrlListType, KeyedAppUrl } from './authorizedUrlListLogic'

function EmptyState({
    experimentId,
    actionId,
    type,
}: {
    type: AuthorizedUrlListType
    actionId?: number | null
    experimentId?: ExperimentIdType | null
}): JSX.Element | null {
    const logic = authorizedUrlListLogic({ experimentId: experimentId ?? null, actionId: actionId ?? null, type })
    const { urlsKeyed, searchTerm, suggestionsLoading, isAddUrlFormVisible } = useValues(logic)
    const { loadSuggestions } = useActions(logic)

    const domainOrUrl = type === AuthorizedUrlListType.RECORDING_DOMAINS ? 'domain' : 'URL'

    // Split suggestions and non-suggestions
    const [suggestionURLs, authorizedURLs] = urlsKeyed.reduce(
        ([suggestions, nonSuggestions], url) => {
            if (url.type === 'suggestion') {
                suggestions.push(url)
            } else {
                nonSuggestions.push(url)
            }
            return [suggestions, nonSuggestions]
        },
        [[], []] as KeyedAppUrl[][]
    )

    const children = useMemo(() => {
        // If there are authorized URLs, never display this empty state
        if (authorizedURLs.length > 0) {
            return null
        }

        // If the add URL form is visible, don't show the empty state either
        if (isAddUrlFormVisible) {
            return null
        }

        // This means no suggested URLs and no search term
        if (searchTerm.length > 0 && suggestionURLs.length === 0) {
            return <>There are no authorized {domainOrUrl}s that match your search.</>
        }

        if (suggestionURLs.length > 0) {
            return (
                <p className="mb-0">
                    There are no authorized {domainOrUrl}s. <br />
                    We've found some URLs you've used PostHog from in the last 3 days. Consider authorizing them.
                    <br />
                    <span>
                        {type === AuthorizedUrlListType.RECORDING_DOMAINS &&
                            ' When no domains are specified, recordings will be authorized on all domains.'}
                    </span>
                </p>
            )
        }

        return (
            <div className="flex flex-row items-center justify-between w-full">
                <p>
                    <span className="font-bold">There are no authorized {domainOrUrl}s.</span>
                    <br />
                    Add one to get started. When you send us events we'll suggest the ones that you should authorize.
                    <br />
                    <span>
                        {type === AuthorizedUrlListType.RECORDING_DOMAINS &&
                            ' When no domains are specified, recordings will be authorized on all domains.'}
                    </span>
                </p>
                <div className="flex flex-col items-end gap-2">
                    <LemonButton
                        onClick={loadSuggestions}
                        disabled={suggestionsLoading}
                        type="secondary"
                        icon={<IconRefresh />}
                        data-attr="toolbar-add-url"
                    >
                        {suggestionsLoading ? 'Fetching...' : 'Fetch suggestions'}
                    </LemonButton>
                    <span className="text-small text-secondary">Sent an event? Refetch suggestions.</span>
                </div>
            </div>
        )
    }, [
        authorizedURLs.length,
        isAddUrlFormVisible,
        searchTerm.length,
        suggestionURLs.length,
        suggestionsLoading,
        type,
        domainOrUrl,
        loadSuggestions,
    ])

    return children ? <div className="border rounded p-4 text-secondary">{children}</div> : null
}

export interface AuthorizedUrlFormProps {
    type: AuthorizedUrlListType
    actionId?: number
    experimentId?: ExperimentIdType
    allowWildCards?: boolean
}

function AuthorizedUrlForm({ actionId, experimentId, type, allowWildCards }: AuthorizedUrlFormProps): JSX.Element {
    const logic = authorizedUrlListLogic({
        actionId: actionId ?? null,
        experimentId: experimentId ?? null,
        type,
        allowWildCards,
    })
    const { isProposedUrlSubmitting } = useValues(logic)
    const { cancelProposingUrl } = useActions(logic)

    return (
        <Form
            logic={authorizedUrlListLogic}
            props={{ actionId, type, experimentId, allowWildCards }}
            formKey="proposedUrl"
            enableFormOnSubmit
            className="w-full space-y-2"
        >
            <LemonField name="url">
                <LemonInput
                    autoFocus
                    placeholder={
                        allowWildCards
                            ? 'Enter a URL or wildcard subdomain (e.g. https://*.posthog.com)'
                            : 'Enter a URL (e.g. https://posthog.com)'
                    }
                    data-attr="url-input"
                />
            </LemonField>
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={cancelProposingUrl}>
                    Cancel
                </LemonButton>
                <LemonButton htmlType="submit" type="primary" disabled={isProposedUrlSubmitting} data-attr="url-save">
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}

export interface AuthorizedUrlListProps {
    actionId?: number
    experimentId?: ExperimentIdType
    query?: string | null
    type: AuthorizedUrlListType
    allowWildCards?: boolean
}

export function AuthorizedUrlList({
    actionId,
    experimentId,
    query,
    type,
    addText = 'Add',
    allowWildCards,
}: AuthorizedUrlListProps & { addText?: string }): JSX.Element {
    const logic = authorizedUrlListLogic({
        experimentId: experimentId ?? null,
        actionId: actionId ?? null,
        type,
        query,
        allowWildCards,
    })

    const {
        urlsKeyed,
        searchTerm,
        launchUrl,
        editUrlIndex,
        isAddUrlFormVisible,
        onlyAllowDomains,
        manualLaunchParamsLoading,
    } = useValues(logic)
    const { addUrl, removeUrl, setSearchTerm, newUrl, setEditUrlIndex, copyLaunchCode } = useActions(logic)

    const noAuthorizedUrls = !urlsKeyed.some((url) => url.type === 'authorized')

    return (
        <div>
            <div className="flex items-center mb-4 gap-2 justify-between">
                <LemonInput
                    placeholder={`Search for authorized ${onlyAllowDomains ? 'domains' : 'URLs'}`}
                    onChange={setSearchTerm}
                    value={searchTerm}
                    className="w-full"
                />
                <LemonButton onClick={newUrl} type="secondary" icon={<IconPlus />} data-attr="toolbar-add-url">
                    {addText}
                </LemonButton>
            </div>
            <div className="space-y-2">
                <EmptyState experimentId={experimentId} actionId={actionId} type={type} />

                {isAddUrlFormVisible && (
                    <div className="border rounded p-2 bg-surface-primary">
                        <AuthorizedUrlForm
                            type={type}
                            actionId={actionId}
                            experimentId={experimentId}
                            allowWildCards={allowWildCards}
                        />
                    </div>
                )}

                {urlsKeyed.map((keyedURL, index) => {
                    const isFirstSuggestion = keyedURL.originalIndex === 0 && keyedURL.type === 'suggestion'

                    return editUrlIndex === index ? (
                        <div className="border rounded p-2 bg-surface-primary">
                            <AuthorizedUrlForm
                                type={type}
                                actionId={actionId}
                                experimentId={experimentId}
                                allowWildCards={allowWildCards}
                            />
                        </div>
                    ) : (
                        <div
                            key={index}
                            className={clsx('border rounded flex items-center p-2 pl-4 bg-surface-primary')}
                        >
                            {keyedURL.type === 'suggestion' && (
                                <Tooltip title={'Seen in ' + keyedURL.count + ' events in the last 3 days'}>
                                    <LemonTag type="highlight" className="mr-4 uppercase cursor-pointer">
                                        Suggestion
                                    </LemonTag>
                                </Tooltip>
                            )}
                            <span title={keyedURL.url} className="flex-1 truncate">
                                {keyedURL.url}
                            </span>
                            <div className="Actions flex space-x-2 shrink-0">
                                {keyedURL.type === 'suggestion' ? (
                                    <LemonButton
                                        onClick={() => addUrl(keyedURL.url)}
                                        icon={<IconPlus />}
                                        data-attr="toolbar-apply-suggestion"
                                        // If there are no authorized urls, highglight the first suggestion
                                        type={noAuthorizedUrls && isFirstSuggestion ? 'primary' : undefined}
                                        active={noAuthorizedUrls && isFirstSuggestion}
                                    >
                                        Apply suggestion
                                    </LemonButton>
                                ) : (
                                    <>
                                        <LemonButton
                                            icon={<IconOpenInApp />}
                                            to={
                                                // toolbar urls are sent through the backend to be validated
                                                // and have toolbar auth information added
                                                type === AuthorizedUrlListType.TOOLBAR_URLS
                                                    ? launchUrl(keyedURL.url)
                                                    : // other urls are simply opened directly
                                                      `${keyedURL.url}${query ?? ''}`
                                            }
                                            targetBlank
                                            tooltip={
                                                type === AuthorizedUrlListType.TOOLBAR_URLS
                                                    ? 'Launch toolbar'
                                                    : 'Launch url'
                                            }
                                            center
                                            data-attr="toolbar-open"
                                            type="secondary"
                                            disabledReason={
                                                keyedURL.url.includes('*')
                                                    ? 'Wildcard domains cannot be launched'
                                                    : undefined
                                            }
                                            sideAction={{
                                                dropdown: {
                                                    placement: 'bottom-start',
                                                    overlay: (
                                                        <div className="px-2 py-1">
                                                            <h3>If launching the toolbar didn't work, </h3>
                                                            <p>
                                                                You can copy the launch code and paste it into the
                                                                browser console on your site.
                                                            </p>
                                                            <p>NB you need to have added posthog to the `window`</p>
                                                            <LemonButton
                                                                icon={<IconCopy />}
                                                                size="small"
                                                                className="float-right"
                                                                type="primary"
                                                                data-attr="copy-manual-toolbar-launch-code"
                                                                onClick={() => {
                                                                    copyLaunchCode(keyedURL.url)
                                                                }}
                                                                loading={manualLaunchParamsLoading}
                                                            >
                                                                Copy launch code
                                                            </LemonButton>
                                                        </div>
                                                    ),
                                                },
                                                'data-attr': 'launch-toolbar-sideaction-dropdown',
                                            }}
                                        >
                                            Launch
                                        </LemonButton>

                                        <LemonButton
                                            icon={<IconPencil />}
                                            onClick={() => setEditUrlIndex(keyedURL.originalIndex)}
                                            tooltip="Edit"
                                            center
                                        />

                                        <LemonButton
                                            icon={<IconTrash />}
                                            tooltip={`Remove ${onlyAllowDomains ? 'domain' : 'URL'}`}
                                            center
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: <>Remove {keyedURL.url} ?</>,
                                                    description: `Are you sure you want to remove this authorized ${
                                                        onlyAllowDomains ? 'domain' : 'URL'
                                                    }?`,
                                                    primaryButton: {
                                                        status: 'danger',
                                                        children: 'Remove',
                                                        onClick: () => removeUrl(index),
                                                    },
                                                    secondaryButton: {
                                                        children: 'Cancel',
                                                    },
                                                })
                                            }}
                                        />
                                    </>
                                )}
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
