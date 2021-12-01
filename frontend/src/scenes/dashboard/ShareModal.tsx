import React, { useState } from 'react'
import { Modal, Switch, Button } from 'antd'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInput } from 'lib/components/CopyToClipboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'

export function ShareModal({ visible, onCancel }: { visible: boolean; onCancel: () => void }): JSX.Element {
    const { dashboard } = useValues(dashboardLogic)
    const { setIsSharedDashboard } = useActions(dashboardLogic)
    const [isShared, setIsShared] = useState(dashboard?.is_shared)

    const url = window.location.origin + '/shared_dashboard/' + dashboard?.share_token

    return dashboard ? (
        <Modal
            visible={visible}
            onCancel={onCancel}
            footer={<Button onClick={onCancel}>Close</Button>}
            title="Share your dashboard with people outside of PostHog."
            destroyOnClose
        >
            <Switch
                onClick={(_, e) => e.stopPropagation()}
                checked={isShared}
                data-attr="share-dashboard-switch"
                onChange={(active) => {
                    setIsShared(active)
                    setIsSharedDashboard(dashboard.id, active)
                }}
            />{' '}
            Share your dashboard
            <br />
            <br />
            {isShared ? (
                <span>
                    Your dashboard is visible to everyone with the link.
                    {dashboard.share_token && (
                        <CopyToClipboardInput data-attr="share-dashboard-link" value={url} description="link" />
                    )}
                    <br />
                    <br />
                    To embed this dashboard on your own website, copy the snippet:
                    <CodeSnippet language={Language.HTML}>
                        {`<iframe width="100%" height="100%" frameborder="0" src="${url}?embed" />`}
                    </CodeSnippet>
                    <small>You can hardcode the height in pixels based on your website to avoid the scrollbar.</small>
                </span>
            ) : (
                'Your dashboard is private.'
            )}
        </Modal>
    ) : (
        <div />
    )
}
