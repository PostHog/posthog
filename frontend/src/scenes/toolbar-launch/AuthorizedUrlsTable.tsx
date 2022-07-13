import React, { useEffect, useState } from 'react'
import './AuthorizedUrlsTable.scss'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { CheckCircleFilled } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { Button, Input } from 'antd'
import { authorizedUrlsLogic, KeyedAppUrl, NEW_URL } from './authorizedUrlsLogic'
import { isMobile, isURL } from 'lib/utils'
import { More } from 'lib/components/LemonButton/More'

interface AuthorizedUrlsTableInterface {
    pageKey?: string
    actionId?: number
}

export function AuthorizedUrlsTable({ pageKey, actionId }: AuthorizedUrlsTableInterface): JSX.Element {
    const logic = authorizedUrlsLogic({ actionId })
    const { appUrlsKeyed, suggestionsLoading, searchTerm, launchUrl, appUrls, editUrlIndex } = useValues(logic)
    const { addUrl, removeUrl, setSearchTerm, updateUrl, newUrl, setEditUrlIndex } = useActions(logic)

    const columns: LemonTableColumns<KeyedAppUrl> = [
        {
            title: 'URLs',
            dataIndex: 'url',
            key: 'url',
            render: function Render(url, record) {
                const [urlUpdatingState, setUrlUpdatingState] = useState(record.url)
                const [errorState, setErrorState] = useState('')
                useEffect(() => setUrlUpdatingState(record.url), [record])
                const save = (): void => {
                    setErrorState('')
                    if (urlUpdatingState === NEW_URL) {
                        removeUrl(record.originalIndex)
                    }
                    // See https://regex101.com/r/UMBc9g/1 for tests
                    if (
                        urlUpdatingState.indexOf('*') > -1 &&
                        !urlUpdatingState.match(/^(.*)\*[^\*]*\.[^\*]+\.[^\*]+$/)
                    ) {
                        setErrorState(
                            'You can only wildcard subdomains. If you wildcard the domain or TLD, people might be able to gain access to your PostHog data.'
                        )
                        return
                    }
                    if (!isURL(urlUpdatingState)) {
                        setErrorState('Please type a valid URL or domain.')
                        return
                    }

                    if (
                        appUrls.indexOf(urlUpdatingState) > -1 &&
                        appUrls.indexOf(urlUpdatingState, record.originalIndex) !== record.originalIndex &&
                        appUrls.indexOf(urlUpdatingState, record.originalIndex + 1) !== record.originalIndex
                    ) {
                        setErrorState('This URL is already registered.')
                        return
                    }

                    updateUrl(record.originalIndex, urlUpdatingState)
                }
                return record.type === 'suggestion' || (url !== NEW_URL && editUrlIndex !== record.originalIndex) ? (
                    <div className={clsx('authorized-url-col', record.type)}>
                        {record.type === 'authorized' && <CheckCircleFilled style={{ marginRight: 4 }} />}
                        {url}
                        {record.type === 'suggestion' && <LemonTag>Suggestion</LemonTag>}
                    </div>
                ) : (
                    <div>
                        <div style={{ display: 'flex' }}>
                            <Input
                                value={urlUpdatingState}
                                onChange={(e) => setUrlUpdatingState(e.target.value)}
                                onPressEnter={save}
                                autoFocus
                                placeholder="Enter a URL or wildcard subdomain (e.g. https://*.posthog.com)"
                                data-attr="url-input"
                            />
                            <Button type="primary" onClick={save} data-attr="url-save">
                                Save
                            </Button>
                        </div>
                        {errorState && <span className="text-small text-danger">{errorState}</span>}
                    </div>
                )
            },
        },
        {
            title: '',
            key: 'actions',
            render: function Render(_, record, index) {
                return (
                    <div className="actions-col">
                        {record.type === 'suggestion' ? (
                            <LemonButton
                                type="secondary"
                                onClick={() => addUrl(record.url)}
                                data-attr="toolbar-apply-suggestion"
                            >
                                Apply suggestion
                            </LemonButton>
                        ) : (
                            <>
                                <LemonButton
                                    type="highlighted"
                                    href={launchUrl(record.url)}
                                    className="mr"
                                    data-attr="toolbar-open"
                                >
                                    Open with Toolbar
                                </LemonButton>
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                fullWidth
                                                type="stealth"
                                                onClick={() => setEditUrlIndex(record.originalIndex)}
                                            >
                                                Edit authorized URL
                                            </LemonButton>
                                            <LemonButton
                                                fullWidth
                                                style={{ color: 'var(--danger)' }}
                                                type="stealth"
                                                onClick={() => removeUrl(index)}
                                            >
                                                Remove authorized URL
                                            </LemonButton>
                                        </>
                                    }
                                />
                            </>
                        )}
                    </div>
                )
            },
        },
    ]

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
                <LemonButton type="primary" onClick={newUrl} data-attr="toolbar-add-url">
                    Add{pageKey === 'toolbar-launch' && ' authorized URL'}
                </LemonButton>
            </div>
            <LemonTable
                className="authorized-urls-table"
                columns={columns}
                dataSource={appUrlsKeyed}
                emptyState={
                    searchTerm
                        ? 'There are no authorized URLs that match your search.'
                        : 'There are no authorized URLs or domains. Add one to get started.'
                }
                loading={suggestionsLoading}
            />
        </div>
    )
}
