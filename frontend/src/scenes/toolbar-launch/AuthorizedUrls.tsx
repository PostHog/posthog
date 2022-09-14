import React from 'react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { LemonButton } from 'lib/components/LemonButton'
import { Popconfirm } from 'antd'
import { authorizedUrlsLogic } from './authorizedUrlsLogic'
import { isMobile } from 'lib/utils'
import { LemonRow } from 'lib/components/LemonRow'
import { IconDelete, IconEdit, IconOpenInApp, IconPlus } from 'lib/components/icons'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { Form } from 'kea-forms'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Field } from 'lib/forms/Field'

interface AuthorizedUrlsTableInterface {
    pageKey?: string
    actionId?: number
}

function EmptyState({
    numberOfResults,
    isSearching,
    isAddingEntry,
}: {
    numberOfResults: number
    isSearching: boolean
    isAddingEntry: boolean
}): JSX.Element | null {
    if (numberOfResults > 0) {
        return null
    }

    return isSearching ? (
        <LemonRow outlined fullWidth size="large" className="AuthorizedUrlRow">
            There are no authorized URLs that match your search.
        </LemonRow>
    ) : isAddingEntry ? null : (
        <LemonRow outlined fullWidth size="large" className="AuthorizedUrlRow">
            There are no authorized URLs or domains. Add one to get started.
        </LemonRow>
    )
}

function AuthorizedUrlForm({ actionId }: { actionId?: number }): JSX.Element {
    const logic = authorizedUrlsLogic({ actionId })
    const { isProposedUrlSubmitting } = useValues(logic)
    const { cancelProposingUrl } = useActions(logic)
    return (
        <Form
            logic={authorizedUrlsLogic}
            props={{ actionId }}
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

export function AuthorizedUrls({ pageKey, actionId }: AuthorizedUrlsTableInterface): JSX.Element {
    const logic = authorizedUrlsLogic({ actionId })
    const { appUrlsKeyed, suggestionsLoading, searchTerm, launchUrl, editUrlIndex, isAddUrlFormVisible } =
        useValues(logic)
    const { addUrl, removeUrl, setSearchTerm, newUrl, setEditUrlIndex } = useActions(logic)

    return (
        <div>
            <div className="flex items-center mb-4 gap-2 justify-between">
                <LemonInput
                    type="search"
                    autoFocus={pageKey === 'toolbar-launch' && !isMobile()}
                    placeholder="Search for authorized URLs"
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
                            <AuthorizedUrlForm actionId={actionId} />
                        </LemonRow>
                    )}
                    <EmptyState
                        numberOfResults={appUrlsKeyed.length}
                        isSearching={searchTerm.length > 0}
                        isAddingEntry={isAddUrlFormVisible}
                    />
                    {appUrlsKeyed.map((keyedAppURL, index) => {
                        return (
                            <div key={index} className={clsx('border rounded flex items-center py-2 px-4 min-h-14')}>
                                {editUrlIndex === index ? (
                                    <AuthorizedUrlForm actionId={actionId} />
                                ) : (
                                    <>
                                        {keyedAppURL.type === 'suggestion' && (
                                            <LemonTag type="highlight" className="mr-4">
                                                Suggestion
                                            </LemonTag>
                                        )}
                                        <span title={keyedAppURL.url} className="flex-1 truncate">
                                            {keyedAppURL.url}
                                        </span>
                                        <div className="Actions flex space-x-2 shrink-0">
                                            {keyedAppURL.type === 'suggestion' ? (
                                                <LemonButton
                                                    onClick={() => addUrl(keyedAppURL.url)}
                                                    icon={<IconPlus />}
                                                    data-attr="toolbar-apply-suggestion"
                                                >
                                                    Apply suggestion
                                                </LemonButton>
                                            ) : (
                                                <>
                                                    <LemonButton
                                                        icon={<IconOpenInApp />}
                                                        to={launchUrl(keyedAppURL.url)}
                                                        targetBlank
                                                        tooltip={'Launch toolbar'}
                                                        center
                                                        className="ActionButton"
                                                        data-attr="toolbar-open"
                                                    >
                                                        Launch
                                                    </LemonButton>

                                                    <LemonButton
                                                        icon={<IconEdit />}
                                                        onClick={() => setEditUrlIndex(keyedAppURL.originalIndex)}
                                                        tooltip={'Edit'}
                                                        center
                                                        className="ActionButton"
                                                    />
                                                    <Popconfirm
                                                        placement="topRight"
                                                        title={
                                                            <>Are you sure you want to remove this authorized url?</>
                                                        }
                                                        onConfirm={() => removeUrl(index)}
                                                    >
                                                        <LemonButton
                                                            icon={<IconDelete />}
                                                            tooltip={'Remove URL'}
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
