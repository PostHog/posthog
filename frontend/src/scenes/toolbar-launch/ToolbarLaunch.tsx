import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { appUrlsLogic, KeyedAppUrl } from 'lib/components/AppEditorLink/appUrlsLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import './ToolbarLaunch.scss'
import { PlusOutlined, EllipsisOutlined, DeleteOutlined, EditOutlined, CheckCircleFilled } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { Popup } from 'lib/components/Popup/Popup'
import { appEditorUrl } from 'lib/components/AppEditorLink/utils'

export const scene: SceneExport = {
    component: ToolbarLaunch,
}

function ToolbarLaunch(): JSX.Element {
    const { appUrlsKeyed, popoverOpen, suggestionsLoading } = useValues(appUrlsLogic)
    const { addUrl, setPopoverOpen, removeUrl } = useActions(appUrlsLogic)

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
        <div className="toolbar-launch-page">
            <PageHeader title="Toolbar" caption="The toolbar launches PostHog right in your app or website." />

            <LemonTable
                className="authorized-urls-table"
                columns={columns}
                dataSource={appUrlsKeyed}
                emptyState="There are no authorized URLs or domains. Add one to get started."
                loading={suggestionsLoading}
            />
        </div>
    )
}
