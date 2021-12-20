import React from 'react'
import './AuthorizedUrlsTable.scss'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { appUrlsLogic, KeyedAppUrl } from 'lib/components/AppEditorLink/appUrlsLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PlusOutlined, EllipsisOutlined, DeleteOutlined, EditOutlined, CheckCircleFilled } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { Popup } from 'lib/components/Popup/Popup'
import { appEditorUrl } from 'lib/components/AppEditorLink/utils'
import { Input } from 'antd'

interface AuthorizedUrlsTableInterface {
    pageKey?: string
}

export function AuthorizedUrlsTable({ pageKey }: AuthorizedUrlsTableInterface): JSX.Element {
    const { appUrlsKeyed, popoverOpen, suggestionsLoading, searchTerm } = useValues(appUrlsLogic)
    const { addUrl, setPopoverOpen, removeUrl, setSearchTerm } = useActions(appUrlsLogic)

    const columns: LemonTableColumns<KeyedAppUrl> = [
        {
            title: 'URLs',
            dataIndex: 'url',
            key: 'url',
            render: function Render(url, record) {
                return (
                    <div className={clsx('authorized-url-col', record.type)}>
                        {record.type === 'authorized' && <CheckCircleFilled style={{ marginRight: 4 }} />}
                        {url}
                        {record.type === 'suggestion' && <LemonTag>Suggestion</LemonTag>}
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
                            <LemonButton type="default" onClick={() => addUrl(record.url)}>
                                <PlusOutlined /> Add as authorized
                            </LemonButton>
                        ) : (
                            <>
                                <a href={appEditorUrl(record.url, undefined, 'inspect')}>
                                    <LemonButton type="highlighted">Launch toolbar</LemonButton>
                                </a>
                                <Popup
                                    visible={popoverOpen === `${index}_${record.url}`}
                                    actionable
                                    onClickOutside={() => setPopoverOpen(null)}
                                    overlay={
                                        <>
                                            <LemonButton fullWidth type="stealth">
                                                <EditOutlined style={{ marginRight: 4 }} /> Edit authorized URL
                                            </LemonButton>
                                            <LemonButton
                                                fullWidth
                                                style={{ color: 'var(--danger)' }}
                                                type="stealth"
                                                onClick={() => removeUrl(index)}
                                            >
                                                <DeleteOutlined style={{ marginRight: 4 }} />
                                                Remove authorized URL
                                            </LemonButton>
                                        </>
                                    }
                                >
                                    <LemonButton
                                        type="stealth"
                                        onClick={() => setPopoverOpen(popoverOpen ? null : `${index}_${record.url}`)}
                                        style={{ marginLeft: 8 }}
                                    >
                                        <EllipsisOutlined
                                            style={{ color: 'var(--primary)', fontSize: 24 }}
                                            className="urls-dropdown-actions"
                                        />
                                    </LemonButton>
                                </Popup>
                            </>
                        )}
                    </div>
                )
            },
        },
    ]

    return (
        <div>
            <div>
                <Input.Search
                    allowClear
                    enterButton
                    placeholder="Search for authorized URLs"
                    style={{ width: 480, maxWidth: '100%', marginBottom: 16 }}
                    value={searchTerm}
                    onChange={(e) => {
                        setSearchTerm(e.target.value)
                    }}
                    autoFocus={pageKey === 'toolbar-launch'}
                />
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
