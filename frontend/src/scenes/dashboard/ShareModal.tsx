import React from 'react'
import { Modal, Button } from 'antd'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInput } from 'lib/components/CopyToClipboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'

export function ShareModal({ visible, onCancel }: { visible: boolean; onCancel: () => void }): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic)
    const { dashboardLoading } = useValues(dashboardsModel)
    const { setIsSharedDashboard } = useActions(dashboardLogic)

    const shareLink = dashboard ? window.location.origin + urls.sharedDashboard(dashboard.share_token) : ''

    return dashboard ? (
        <Modal
            visible={visible}
            onCancel={onCancel}
            footer={<Button onClick={onCancel}>Close</Button>}
            title="Dashboard sharing"
            destroyOnClose
        >
            <LemonSwitch
                label="Share dashboard publicly"
                checked={dashboard.is_shared}
                loading={dashboardLoading}
                data-attr="share-dashboard-switch"
                onChange={(active) => {
                    setIsSharedDashboard(dashboard.id, active)
                }}
                block
            />
            {dashboard.is_shared ? (
                <>
                    {dashboard.share_token && (
                        <CopyToClipboardInput
                            data-attr="share-dashboard-link"
                            value={shareLink}
                            description="link"
                            className="mb"
                        />
                    )}
                    To embed this dashboard on your website, copy this snippet:
                    <CodeSnippet language={Language.HTML}>
                        {`<iframe width="100%" height="100%" frameborder="0" src="${shareLink}?embedded" />`}
                    </CodeSnippet>
                </>
            ) : null}
        </Modal>
    ) : null
}
