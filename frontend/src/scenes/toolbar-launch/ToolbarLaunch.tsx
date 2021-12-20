import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { appUrlsLogic, KeyedAppUrl } from 'lib/components/AppEditorLink/appUrlsLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import './ToolbarLaunch.scss'
import { PlusOutlined } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'

export const scene: SceneExport = {
    component: ToolbarLaunch,
    //logic: toolbarLaunchLogic,
}

function ToolbarLaunch(): JSX.Element {
    const { appUrlsKeyed } = useValues(appUrlsLogic)
    const { addUrl, launchAtUrl } = useActions(appUrlsLogic)

    const columns: LemonTableColumns<KeyedAppUrl> = [
        {
            title: 'Authorized URL',
            dataIndex: 'url',
            key: 'url',
            render: function Render(url, record) {
                return (
                    <div className={clsx('authorized-url-col', record.type)}>
                        {url}
                        {record.type === 'suggestion' && <LemonTag>Suggestion</LemonTag>}
                    </div>
                )
            },
        },
        {
            title: '',
            key: 'actions',
            render: function Render(_, record) {
                return (
                    <div className="actions-col">
                        {record.type === 'suggestion' ? (
                            <LemonButton type="default" onClick={() => addUrl(record.url)}>
                                <PlusOutlined /> Add as authorized
                            </LemonButton>
                        ) : (
                            <>
                                <LemonButton type="highlighted" onClick={() => launchAtUrl(record.url)}>
                                    Launch toolbar
                                </LemonButton>
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
            />
        </div>
    )
}
