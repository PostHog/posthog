import React from 'react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { LemonButton } from 'lib/components/LemonButton'
import { Popconfirm } from 'antd'
import {
    AuthorizedUrlListType as AuthorizedUrlListType,
    authorizedUrlListLogic,
    AuthorizedUrlListProps,
} from './authorizedUrlListLogic'
import { isMobile } from 'lib/utils'
import { LemonRow } from 'lib/components/LemonRow'
import { IconDelete, IconEdit, IconOpenInApp, IconPlus } from 'lib/components/icons'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { Form } from 'kea-forms'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Field } from 'lib/forms/Field'

function EmptyState({
    numberOfResults,
    isSearching,
    isAddingEntry,
    onlyAllowDomains,
}: {
    numberOfResults: number
    isSearching: boolean
    isAddingEntry: boolean
    onlyAllowDomains: boolean
}): JSX.Element | null {
    if (numberOfResults > 0) {
        return null
    }

    return isSearching ? (
        <LemonRow outlined fullWidth size="large" className="AuthorizedUrlRow">
            There are no authorized {onlyAllowDomains ? 'domains' : 'URLs'} that match your search.
        </LemonRow>
    ) : isAddingEntry ? null : (
        <LemonRow outlined fullWidth size="large" className="AuthorizedUrlRow">
            There are no authorized {onlyAllowDomains ? 'domains' : 'URLs'}. Add one to get started.
        </LemonRow>
    )
}

function AuthorizedUrlForm({ actionId, type, pageKey }: AuthorizedUrlListProps): JSX.Element {
    const logic = authorizedUrlListLogic({ actionId, type, pageKey })
    const { isProposedUrlSubmitting } = useValues(logic)
    const { cancelProposingUrl } = useActions(logic)
    return (
        <Form
            logic={authorizedUrlListLogic}
            props={{ actionId, type, pageKey }}
            formKey="proposedUrl"
            enableFormOnSubmit
            className="w-full space-y-2"
        >
            <Field name="url">
                <LemonInput
                    autoFocus
                    placeholder="Enter a URL or wildcard subdomain (e.g. https://*.posthog.com)"
                    data-attr="url-input"
                />
            </Field>
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

export function AuthorizedUrlList({ pageKey, actionId, type }: AuthorizedUrlListProps): JSX.Element {
    const logic = authorizedUrlListLogic({ pageKey, actionId, type })
    const {
        urlsKeyed,
        suggestionsLoading,
        searchTerm,
        launchUrl,
        editUrlIndex,
        isAddUrlFormVisible,
        onlyAllowDomains,
    } = useValues(logic)
    const { addUrl, removeUrl, setSearchTerm, newUrl, setEditUrlIndex } = useActions(logic)

    return (
        <div>
            <div className="flex items-center mb-4 gap-2 justify-between">
                <LemonInput
                    type="search"
                    autoFocus={pageKey === 'toolbar-launch' && !isMobile()}
                    placeholder={`Search for authorized ${onlyAllowDomains ? 'domains' : 'URLs'}`}
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
                <LemonButton onClick={newUrl} type="secondary" icon={<IconPlus />} data-attr="toolbar-add-url">
                    Add{pageKey === 'toolbar-launch' && ' authorized URL'}
                </LemonButton>
            </div>
            {suggestionsLoading ? (
                <LemonRow outlined fullWidth size="large" key={-1}>
                    <Spinner className="text-xl" />
                </LemonRow>
            ) : (
                <div className="space-y-2">
                    {isAddUrlFormVisible && (
                        <LemonRow outlined fullWidth size="large">
                            <AuthorizedUrlForm type={type} actionId={actionId} pageKey={pageKey} />
                        </LemonRow>
                    )}
                    <EmptyState
                        numberOfResults={urlsKeyed.length}
                        isSearching={searchTerm.length > 0}
                        isAddingEntry={isAddUrlFormVisible}
                        onlyAllowDomains
                    />
                    {urlsKeyed.map((keyedURL, index) => {
                        return (
                            <div key={index} className={clsx('border rounded flex items-center py-2 px-4 min-h-14')}>
                                {editUrlIndex === index ? (
                                    <AuthorizedUrlForm type={type} actionId={actionId} pageKey={pageKey} />
                                ) : (
                                    <>
                                        {keyedURL.type === 'suggestion' && (
                                            <LemonTag type="highlight" className="mr-4">
                                                Suggestion
                                            </LemonTag>
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
                                                >
                                                    Apply suggestion
                                                </LemonButton>
                                            ) : (
                                                <>
                                                    <LemonButton
                                                        icon={<IconOpenInApp />}
                                                        to={launchUrl(keyedURL.url)}
                                                        targetBlank
                                                        tooltip={
                                                            type === AuthorizedUrlListType.TOOLBAR_URLS
                                                                ? 'Launch toolbar'
                                                                : 'Launch url'
                                                        }
                                                        center
                                                        className="ActionButton"
                                                        data-attr="toolbar-open"
                                                    >
                                                        Launch
                                                    </LemonButton>

                                                    <LemonButton
                                                        icon={<IconEdit />}
                                                        onClick={() => setEditUrlIndex(keyedURL.originalIndex)}
                                                        tooltip={'Edit'}
                                                        center
                                                        className="ActionButton"
                                                    />
                                                    <Popconfirm
                                                        placement="topRight"
                                                        title={
                                                            <>
                                                                Are you sure you want to remove this authorized{' '}
                                                                {onlyAllowDomains ? 'domain' : 'URL'}?
                                                            </>
                                                        }
                                                        onConfirm={() => removeUrl(index)}
                                                    >
                                                        <LemonButton
                                                            icon={<IconDelete />}
                                                            tooltip={`Remove ${onlyAllowDomains ? 'domain' : 'URL'}`}
                                                            center
                                                            className="ActionButton"
                                                        />
                                                    </Popconfirm>
                                                </>
                                            )}
                                        </div>
                                    </>
                                )}
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
