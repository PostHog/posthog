import React from 'react'
import './AuthorizedUrls.scss'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { LemonButton } from 'lib/components/LemonButton'
import { Input } from 'antd'
import { authorizedUrlsLogic } from './authorizedUrlsLogic'
import { isMobile } from 'lib/utils'
import { LemonRow } from 'lib/components/LemonRow'
import { IconDelete, IconEdit, IconOpenInApp, IconPlus } from 'lib/components/icons'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { Form } from 'kea-forms'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Field } from 'lib/forms/Field'
import Typography from 'antd/lib/typography'

interface AuthorizedUrlsTableInterface {
    pageKey?: string
    actionId?: number
}

function EmptyState({
    numberOfResults,
    isSearching,
}: {
    numberOfResults: number
    isSearching: boolean
}): JSX.Element | null {
    if (numberOfResults > 0) {
        return null
    }

    return isSearching ? (
        <LemonRow outlined fullWidth size="large" className={clsx('AuthorizedUrlRow')}>
            There are no authorized URLs that match your search.
        </LemonRow>
    ) : (
        <LemonRow outlined fullWidth size="large" className={clsx('AuthorizedUrlRow')}>
            There are no authorized URLs or domains. Add one to get started.
        </LemonRow>
    )
}

function AuthorizedUrlForm({ actionId }: { actionId?: number }): JSX.Element {
    const logic = authorizedUrlsLogic({ actionId })
    const { isProposedUrlSubmitting, proposedUrlHasErrors } = useValues(logic)
    const { cancelProposingUrl } = useActions(logic)
    return (
        <Form
            logic={authorizedUrlsLogic}
            props={{ actionId }}
            formKey="proposedUrl"
            enableFormOnSubmit
            className="AuthorizedURLForm"
        >
            <Field name="url">
                <LemonInput autoFocus placeholder="Enter a URL or wildcard subdomain (e.g. https://*.posthog.com)" />
            </Field>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <LemonButton
                    htmlType="submit"
                    type="primary"
                    className="form-submit"
                    disabled={isProposedUrlSubmitting || proposedUrlHasErrors}
                >
                    Save
                </LemonButton>
                <LemonButton type="secondary" onClick={cancelProposingUrl}>
                    Cancel
                </LemonButton>
            </div>
        </Form>
    )
}

export function AuthorizedUrls({ pageKey, actionId }: AuthorizedUrlsTableInterface): JSX.Element {
    const logic = authorizedUrlsLogic({ actionId })
    const { appUrlsKeyed, suggestionsLoading, searchTerm, launchUrl, editUrlIndex } = useValues(logic)
    const { addUrl, removeUrl, setSearchTerm, newUrl, setEditUrlIndex } = useActions(logic)

    return (
        <div>
            <div className="flex-center mb">
                <div style={{ flexGrow: 1 }}>
                    <Input.Search
                        allowClear
                        enterButton
                        placeholder="Search for authorized URLs"
                        style={{ maxWidth: 480 }}
                        value={searchTerm}
                        onChange={(e) => {
                            setSearchTerm(e.target.value)
                        }}
                        autoFocus={pageKey === 'toolbar-launch' && !isMobile()}
                    />
                </div>
                <LemonButton onClick={newUrl} outlined={true} icon={<IconPlus />}>
                    Add{pageKey === 'toolbar-launch' && ' authorized URL'}
                </LemonButton>
            </div>
            {suggestionsLoading ? (
                <LemonRow outlined fullWidth size="large" key={-1} className={clsx('AuthorizedUrlRow')}>
                    <Spinner size="md" />
                </LemonRow>
            ) : (
                <>
                    {editUrlIndex === -1 && (
                        <LemonRow outlined fullWidth size="large" className={clsx('AuthorizedUrlRow')}>
                            <AuthorizedUrlForm actionId={actionId} />
                        </LemonRow>
                    )}
                    <EmptyState numberOfResults={appUrlsKeyed.length} isSearching={searchTerm.length > 0} />
                    {appUrlsKeyed.map((keyedAppURL, index) => {
                        return (
                            <LemonRow
                                outlined
                                fullWidth
                                size="large"
                                key={index}
                                className={clsx('AuthorizedUrlRow', keyedAppURL.type)}
                            >
                                {editUrlIndex === index ? (
                                    <AuthorizedUrlForm actionId={actionId} />
                                ) : (
                                    <>
                                        <div className="Url">
                                            {keyedAppURL.type === 'suggestion' && (
                                                <LemonTag type="highlight">Suggestion</LemonTag>
                                            )}
                                            <Typography.Text ellipsis={{ tooltip: keyedAppURL.url }}>
                                                {keyedAppURL.url}
                                            </Typography.Text>
                                        </div>
                                        <div className="Actions">
                                            {keyedAppURL.type === 'suggestion' ? (
                                                <LemonButton
                                                    onClick={() => addUrl(keyedAppURL.url)}
                                                    icon={<IconPlus />}
                                                    outlined={false}
                                                    style={{ paddingRight: 0, paddingLeft: 0 }}
                                                >
                                                    Apply suggestion
                                                </LemonButton>
                                            ) : (
                                                <>
                                                    <LemonButton
                                                        fullWidth
                                                        icon={<IconOpenInApp />}
                                                        href={launchUrl(keyedAppURL.url)}
                                                        tooltip={'Launch toolbar'}
                                                        center
                                                        className="ActionButton"
                                                    />

                                                    <LemonButton
                                                        fullWidth
                                                        icon={<IconEdit />}
                                                        onClick={() => setEditUrlIndex(keyedAppURL.originalIndex)}
                                                        tooltip={'Edit'}
                                                        center
                                                        className="ActionButton"
                                                    />
                                                    <LemonButton
                                                        fullWidth
                                                        icon={<IconDelete />}
                                                        onClick={() => removeUrl(index)}
                                                        tooltip={'Remove URL'}
                                                        center
                                                        className="ActionButton"
                                                    />
                                                </>
                                            )}
                                        </div>
                                    </>
                                )}
                            </LemonRow>
                        )
                    })}
                </>
            )}
        </div>
    )
}
