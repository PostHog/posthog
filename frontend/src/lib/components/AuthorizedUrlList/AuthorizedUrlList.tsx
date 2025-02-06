import { IconInfo, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CodeLine, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { IconOpenInApp, IconRefresh } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useMemo, useState } from 'react'

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
                    <span className="text-small text-muted-alt">Sent an event? Refetch suggestions.</span>
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

    return children ? <div className="border rounded p-4 text-muted-alt">{children}</div> : null
}

export interface AuthorizedUrlFormProps {
    type: AuthorizedUrlListType
    actionId?: number
    experimentId?: ExperimentIdType
    allowWildCards?: boolean
}

/**
 * relies on being inside a bind logic block for the authorizedUrlListLogic
 */
function AuthorizedUrlForm({ actionId, experimentId, type, allowWildCards }: AuthorizedUrlFormProps): JSX.Element {
    const { isProposedUrlSubmitting } = useValues(authorizedUrlListLogic)
    const { cancelProposingUrl } = useActions(authorizedUrlListLogic)

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

/**
 * relies on being inside a bind logic block for the authorizedUrlListLogic
 */
function ViewURLRow({
    keyedURL,
    isFirstSuggestion,
    type,
    query,
    itemIndex,
}: {
    keyedURL: KeyedAppUrl
    isFirstSuggestion?: boolean
    query?: string | null
    type: AuthorizedUrlListType
    itemIndex: number
}): JSX.Element {
    const { urlsKeyed, launchUrl, onlyAllowDomains, manualLaunchParams, manualLaunchParamsLoading } =
        useValues(authorizedUrlListLogic)
    const { addUrl, removeUrl, setEditUrlIndex, loadManualLaunchParams } = useActions(authorizedUrlListLogic)

    const noAuthorizedUrls = !urlsKeyed.some((url) => url.type === 'authorized')

    const [showManualHelp, setShowManualHelp] = useState(false)

    return (
        <div className="border rounded flex flex-col items-center py-2 px-4 bg-bg-light space-y-2">
            <div className="flex flex-row w-full items-center space-x-2">
                {keyedURL.type === 'suggestion' ? (
                    <Tooltip title={'Seen in ' + keyedURL.count + ' events in the last 3 days'}>
                        <LemonTag type="highlight" className="uppercase cursor-pointer">
                            Suggestion
                        </LemonTag>
                    </Tooltip>
                ) : (
                    <LemonButton
                        icon={<IconInfo />}
                        tooltip="If you cannot automatically launch the toolbar, you can try this manual approach."
                        center
                        onClick={() => {
                            setShowManualHelp(!showManualHelp)
                        }}
                    />
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
                                tooltip={type === AuthorizedUrlListType.TOOLBAR_URLS ? 'Launch toolbar' : 'Launch url'}
                                center
                                data-attr="toolbar-open"
                                disabledReason={
                                    keyedURL.url.includes('*') ? 'Wildcard domains cannot be launched' : undefined
                                }
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
                                            onClick: () => removeUrl(itemIndex),
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
            <div className={clsx('w-full', !showManualHelp && 'hidden')}>
                <LemonBanner type="info">
                    <h2>If you cannot launch the toolbar...</h2>
                    <p>
                        If you can't launch the toolbar normally. Try pasting the code below into the console of your
                        site. NB you have to set `window.posthog` to your instance of PostHog for this to work.
                    </p>

                    {manualLaunchParams ? (
                        <div className={clsx('flex flex-row items-center gap-2')}>
                            <CodeLine
                                text={`window.posthog.loadToolbar(${manualLaunchParams})`}
                                wrapLines={true}
                                language={Language.JavaScript}
                            />
                            <CopyToClipboardInline
                                description="code to paste into the console"
                                explicitValue={`window.posthog.loadToolbar(${manualLaunchParams})`}
                            />
                        </div>
                    ) : (
                        <div className={clsx('flex flex-row items-center gap-2 justify-end')}>
                            <LemonButton
                                onClick={() => loadManualLaunchParams(keyedURL.url)}
                                type="secondary"
                                icon={<IconRefresh />}
                                loading={manualLaunchParamsLoading}
                            >
                                Load toolbar launch code
                            </LemonButton>
                        </div>
                    )}
                </LemonBanner>
            </div>
        </div>
    )
}

export function AuthorizedUrlList({
    actionId,
    experimentId,
    query,
    type,
    addText = 'Add',
    allowWildCards,
}: AuthorizedUrlListProps & { addText?: string }): JSX.Element {
    const listLogicProps = {
        experimentId: experimentId ?? null,
        actionId: actionId ?? null,
        type,
        query,
        allowWildCards,
    }
    const logic = authorizedUrlListLogic(listLogicProps)

    const { urlsKeyed, searchTerm, editUrlIndex, isAddUrlFormVisible, onlyAllowDomains } = useValues(logic)
    const { setSearchTerm, newUrl } = useActions(logic)

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
                    <div className="border rounded p-2 bg-bg-light">
                        <AuthorizedUrlForm
                            type={type}
                            actionId={actionId}
                            experimentId={experimentId}
                            allowWildCards={allowWildCards}
                        />
                    </div>
                )}
                <BindLogic logic={authorizedUrlListLogic} props={listLogicProps}>
                    {urlsKeyed.map((keyedURL, index) => {
                        return editUrlIndex === index ? (
                            <div className="border rounded p-2 bg-bg-light">
                                <AuthorizedUrlForm
                                    type={type}
                                    actionId={actionId}
                                    experimentId={experimentId}
                                    allowWildCards={allowWildCards}
                                />
                            </div>
                        ) : (
                            <ViewURLRow
                                key={index}
                                keyedURL={keyedURL}
                                isFirstSuggestion={keyedURL.originalIndex === 0 && keyedURL.type === 'suggestion'}
                                type={type}
                                query={query}
                                itemIndex={index}
                            />
                        )
                    })}
                </BindLogic>
            </div>
        </div>
    )
}
