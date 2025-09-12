import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCopy, IconPencil, IconPlus, IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconOpenInApp } from 'lib/lemon-ui/icons'

import { ExperimentIdType } from '~/types'

import { AuthorizedUrlForm } from './AuthorizedUrlForm'
import { EmptyState } from './EmptyState'
import { AuthorizedUrlListType, authorizedUrlListLogic } from './authorizedUrlListLogic'

export interface AuthorizedUrlListProps {
    type: AuthorizedUrlListType
    actionId?: number
    experimentId?: ExperimentIdType
    query?: string | null
    allowWildCards?: boolean
    displaySuggestions?: boolean
}

export function AuthorizedUrlList({
    actionId,
    experimentId,
    query,
    type,
    addText = 'Add new authorized URL',
    allowWildCards,
    displaySuggestions = true,
}: AuthorizedUrlListProps & { addText?: string }): JSX.Element {
    const logic = authorizedUrlListLogic({
        experimentId: experimentId ?? null,
        actionId: actionId ?? null,
        type,
        query,
        allowWildCards,
    })

    const { urlsKeyed, launchUrl, editUrlIndex, isAddUrlFormVisible, onlyAllowDomains, manualLaunchParamsLoading } =
        useValues(logic)
    const { addUrl, removeUrl, newUrl, setEditUrlIndex, copyLaunchCode } = useActions(logic)

    const noAuthorizedUrls = !urlsKeyed.some((url) => url.type === 'authorized')

    return (
        <div className="flex flex-col gap-2">
            <EmptyState
                experimentId={experimentId}
                actionId={actionId}
                type={type}
                displaySuggestions={displaySuggestions}
            />

            {isAddUrlFormVisible ? (
                <div className="border rounded p-2 bg-surface-primary">
                    <AuthorizedUrlForm
                        type={type}
                        actionId={actionId}
                        experimentId={experimentId}
                        allowWildCards={allowWildCards}
                    />
                </div>
            ) : (
                <LemonButton
                    className="w-full"
                    onClick={newUrl}
                    type="secondary"
                    icon={<IconPlus />}
                    data-attr="toolbar-add-url"
                >
                    {addText}
                </LemonButton>
            )}

            {urlsKeyed.map((keyedURL, index) => {
                // If there are no authorized urls, highlight the first suggestion
                const isFirstSuggestion = keyedURL.originalIndex === 0 && keyedURL.type === 'suggestion'
                const isHighlighted = noAuthorizedUrls && isFirstSuggestion

                if (!displaySuggestions && keyedURL.type === 'suggestion') {
                    return null
                }

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
                    <div key={index} className={clsx('border rounded flex items-center p-2 pl-4 bg-surface-primary')}>
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
                        <div className="Actions flex deprecated-space-x-2 shrink-0">
                            {keyedURL.type === 'suggestion' ? (
                                <LemonButton
                                    onClick={() => addUrl(keyedURL.url)}
                                    icon={<IconPlus />}
                                    data-attr="toolbar-apply-suggestion"
                                    type={isHighlighted ? 'primary' : undefined}
                                    active={isHighlighted}
                                >
                                    Apply suggestion
                                </LemonButton>
                            ) : (
                                <>
                                    <LemonButton
                                        icon={<IconOpenInApp />}
                                        to={
                                            // toolbar urls and web analytics urls are sent through the backend to be validated
                                            // and have toolbar auth information added
                                            type === AuthorizedUrlListType.TOOLBAR_URLS ||
                                            type === AuthorizedUrlListType.WEB_ANALYTICS
                                                ? launchUrl(keyedURL.url)
                                                : // other urls are simply opened directly
                                                  `${keyedURL.url}${query ?? ''}`
                                        }
                                        targetBlank
                                        tooltip={
                                            type === AuthorizedUrlListType.TOOLBAR_URLS ||
                                            type === AuthorizedUrlListType.WEB_ANALYTICS
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
                                                            You can copy the launch code and paste it into the browser
                                                            console on your site.
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
    )
}
