import React from 'react'
import './AuthorizedUrls.scss'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { LemonButton } from 'lib/components/LemonButton'
import { Input, Popconfirm } from 'antd'
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
        <LemonRow outlined fullWidth size="large" className={clsx('AuthorizedUrlRow')}>
            There are no authorized URLs that match your search.
        </LemonRow>
    ) : isAddingEntry ? null : (
        <LemonRow outlined fullWidth size="large" className={clsx('AuthorizedUrlRow')}>
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
            className="AuthorizedURLForm full-width"
        >
            <Field name="url">
                <LemonInput autoFocus placeholder="Enter a URL or wildcard subdomain (e.g. https://*.posthog.com)" />
            </Field>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <LemonButton type="secondary" onClick={cancelProposingUrl}>
                    Cancel
                </LemonButton>
                <LemonButton
                    htmlType="submit"
                    type="primary"
                    className="form-submit ml"
                    disabled={isProposedUrlSubmitting}
                >
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
                    {isAddUrlFormVisible && (
                        <LemonRow outlined fullWidth size="large" className={clsx('AuthorizedUrlRow')}>
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
                            <LemonRow
                                outlined
                                fullWidth
                                size="tall"
                                key={index}
                                className={clsx('AuthorizedUrlRow', keyedAppURL.type, 'flex-center', 'mb-05', 'mr')}
                            >
                                {editUrlIndex === index ? (
                                    <AuthorizedUrlForm actionId={actionId} />
                                ) : (
                                    <>
                                        <div className="Url flex-grow">
                                            {keyedAppURL.type === 'suggestion' && (
                                                <LemonTag type="highlight mr">Suggestion</LemonTag>
                                            )}
                                            <Typography.Text
                                                ellipsis={{ tooltip: keyedAppURL.url }}
                                                className="text-muted"
                                            >
                                                {keyedAppURL.url}
                                            </Typography.Text>
                                        </div>
                                        <div className="Actions flex flex-row">
                                            {keyedAppURL.type === 'suggestion' ? (
                                                <LemonButton
                                                    onClick={() => addUrl(keyedAppURL.url)}
                                                    icon={<IconPlus />}
                                                    outlined={false}
                                                >
                                                    Apply suggestion
                                                </LemonButton>
                                            ) : (
                                                <>
                                                    <LemonButton
                                                        icon={<IconOpenInApp />}
                                                        href={launchUrl(keyedAppURL.url)}
                                                        tooltip={'Launch toolbar'}
                                                        center
                                                        className="ActionButton mr"
                                                    />

                                                    <LemonButton
                                                        icon={<IconEdit />}
                                                        onClick={() => setEditUrlIndex(keyedAppURL.originalIndex)}
                                                        tooltip={'Edit'}
                                                        center
                                                        className="ActionButton mr"
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
                                                            className="ActionButton mr-05"
                                                        />
                                                    </Popconfirm>
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
