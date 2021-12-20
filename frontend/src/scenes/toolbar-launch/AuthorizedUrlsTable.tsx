import React, { useEffect, useState } from 'react'
import './AuthorizedUrlsTable.scss'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PlusOutlined, EllipsisOutlined, DeleteOutlined, EditOutlined, CheckCircleFilled } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { Popup } from 'lib/components/Popup/Popup'
import { Button, Input } from 'antd'
import { authorizedUrlsLogic, KeyedAppUrl, NEW_URL } from './authorizedUrlsLogic'

interface AuthorizedUrlsTableInterface {
    pageKey?: string
    actionId?: number
}

export function AuthorizedUrlsTable({ pageKey, actionId }: AuthorizedUrlsTableInterface): JSX.Element {
    const logic = authorizedUrlsLogic({ actionId })
    const { appUrlsKeyed, popoverOpen, suggestionsLoading, searchTerm, launchUrl } = useValues(logic)
    const { addUrl, setPopoverOpen, removeUrl, setSearchTerm, updateUrl, newUrl } = useActions(logic)

    const columns: LemonTableColumns<KeyedAppUrl> = [
        {
            title: 'URLs',
            dataIndex: 'url',
            key: 'url',
            render: function Render(url, record) {
                const [urlUpdatingState, setUrlUpdatingState] = useState(record.url)
                useEffect(() => setUrlUpdatingState(record.url), [record])
                return url !== NEW_URL ? (
                    <div className={clsx('authorized-url-col', record.type)}>
                        {record.type === 'authorized' && <CheckCircleFilled style={{ marginRight: 4 }} />}
                        {url}
                        {record.type === 'suggestion' && <LemonTag>Suggestion</LemonTag>}
                    </div>
                ) : (
                    <div>
                        <Input
                            value={urlUpdatingState}
                            onChange={(e) => setUrlUpdatingState(e.target.value)}
                            onPressEnter={() => updateUrl(record.originalIndex, urlUpdatingState)}
                            autoFocus
                        />
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
                                <a href={launchUrl(record.url)}>
                                    <LemonButton type="highlighted">Launch toolbar</LemonButton>
                                </a>
                                <Popup
                                    visible={popoverOpen === `${index}_${record.url}`}
                                    actionable
                                    onClickOutside={() => setPopoverOpen(null)}
                                    onClickInside={() => setPopoverOpen(null)}
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
                        autoFocus={pageKey === 'toolbar-launch'}
                    />
                </div>
                <Button type="primary" icon={<PlusOutlined />} onClick={newUrl}>
                    Add{pageKey === 'toolbar-launch' && ' authorized domain'}
                </Button>
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
