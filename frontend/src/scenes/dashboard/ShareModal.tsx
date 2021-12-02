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
            <p>
                <Switch
                    onClick={(_, e) => e.stopPropagation()}
                    checked={isShared}
                    data-attr="share-dashboard-switch"
                    onChange={(active) => {
                        setIsShared(active)
                        setIsSharedDashboard(dashboard.id, active)
                    }}
                    style={{ marginRight: 8 }}
                />
                Share your dashboard
            </p>
            {isShared ? (
                <>
                    <p>
                        Your dashboard is visible to everyone with the link:
                        {dashboard.share_token && (
                            <CopyToClipboardInput data-attr="share-dashboard-link" value={url} description="link" />
                        )}
                    </p>
                    To embed this dashboard on your own website, copy this snippet:
                    <CodeSnippet language={Language.HTML}>
                        {`<iframe width="100%" height="100%" frameborder="0" src="${url}?embedded" />`}
                    </CodeSnippet>
                    <small>
                        Modify attributes <code>width</code> and <code>height</code> to optimize the embed's size for
                        your website.
                    </small>
                </>
            ) : (
                'Your dashboard is private.'
            )}
        </Modal>
    ) : (
        <div />
    )
}
