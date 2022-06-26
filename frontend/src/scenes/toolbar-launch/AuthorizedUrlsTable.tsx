import React from 'react'
import './AuthorizedUrlsTable.scss'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { LemonButton } from 'lib/components/LemonButton'
import { Input } from 'antd'
import { authorizedUrlsLogic, NEW_URL } from './authorizedUrlsLogic'
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

function AuthorizedUrlForm({ actionId }: { actionId?: number }): JSX.Element {
    const logic = authorizedUrlsLogic({ actionId })
    const { editUrlIndex, isProposedUrlSubmitting, appUrls } = useValues(logic)
    return (
        <Form
            logic={authorizedUrlsLogic}
            props={{ actionId }}
            formKey="proposedUrl"
            enableFormOnSubmit
            className="AuthorizedURLForm"
        >
            <Field name="url" label="">
                <LemonInput
                    defaultValue={editUrlIndex && editUrlIndex >= 0 ? appUrls[editUrlIndex] : NEW_URL}
                    autoFocus
                    placeholder="Enter a URL or wildcard subdomain (e.g. https://*.posthog.com)"
                />
            </Field>
            <LemonButton htmlType="submit" type="primary" className="form-submit" disabled={isProposedUrlSubmitting}>
                Save
            </LemonButton>
        </Form>
    )
}

export function AuthorizedUrlsTable({ pageKey, actionId }: AuthorizedUrlsTableInterface): JSX.Element {
    const logic = authorizedUrlsLogic({ actionId })
    const { appUrlsKeyed, suggestionsLoading, searchTerm, launchUrl, editUrlIndex } = useValues(logic)
    const { addUrl, removeUrl, setSearchTerm, newUrl, setEditUrlIndex } = useActions(logic)

    // const columns: LemonTableColumns<KeyedAppUrl> = [
    //     {
    //         title: 'URLs',
    //         dataIndex: 'url',
    //         key: 'url',
    //         render: function Render(url, record) {
    //             return record.type === 'suggestion' || (url !== NEW_URL && editUrlIndex !== record.originalIndex) ? (
    //                 <div className={clsx('authorized-url-col', record.type)}>
    //                     {record.type === 'authorized' && <CheckCircleFilled style={{ marginRight: 4 }} />}
    //                     {url}
    //                     {record.type === 'suggestion' && <LemonTag>Suggestion</LemonTag>}
    //                 </div>
    //             ) : (
    //                 <div>

    //                 </div>
    //             )
    //         },
    //     },
    //     {
    //         title: '',
    //         key: 'actions',
    //         render: function Render(_, record, index) {
    //             return (
    //                 <div className="actions-col">
    //                     {record.type === 'suggestion' ? (
    //                         <LemonButton type="secondary" onClick={() => addUrl(record.url)}>
    //                             Apply suggestion
    //                         </LemonButton>
    //                     ) : (
    //                         <>
    //                             <LemonButton type="highlighted" href={launchUrl(record.url)} className="mr">
    //                                 Open with Toolbar
    //                             </LemonButton>
    //                             <More
    //                                 overlay={
    //                                     <>
    //                                         <LemonButton
    //                                             fullWidth
    //                                             type="stealth"
    //                                             onClick={() => setEditUrlIndex(record.originalIndex)}
    //                                         >
    //                                             Edit authorized URL
    //                                         </LemonButton>
    //                                         <LemonButton
    //                                             fullWidth
    //                                             style={{ color: 'var(--danger)' }}
    //                                             type="stealth"
    //                                             onClick={() => removeUrl(index)}
    //                                         >
    //                                             Remove authorized URL
    //                                         </LemonButton>
    //                                     </>
    //                                 }
    //                             />
    //                         </>
    //                     )}
    //                 </div>
    //             )
    //         },
    //     },
    // ]

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
                                            <>
                                                {keyedAppURL.type === 'suggestion' && (
                                                    <LemonTag type="highlight">Suggestion</LemonTag>
                                                )}
                                                {keyedAppURL.url}
                                            </>
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
                                                    />

                                                    <LemonButton
                                                        fullWidth
                                                        icon={<IconEdit />}
                                                        onClick={() => setEditUrlIndex(keyedAppURL.originalIndex)}
                                                        tooltip={'Edit'}
                                                        center
                                                    />
                                                    <LemonButton
                                                        fullWidth
                                                        icon={<IconDelete />}
                                                        onClick={() => removeUrl(index)}
                                                        tooltip={'Remove URL'}
                                                        center
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
            {/*<LemonTable*/}
            {/*    className="authorized-urls-table"*/}
            {/*    columns={columns}*/}
            {/*    dataSource={appUrlsKeyed}*/}
            {/*    emptyState={*/}
            {/*        searchTerm*/}
            {/*            ? 'There are no authorized URLs that match your search.'*/}
            {/*            : 'There are no authorized URLs or domains. Add one to get started.'*/}
            {/*    }*/}
            {/*    loading={suggestionsLoading}*/}
            {/*/>*/}
        </div>
    )
}
