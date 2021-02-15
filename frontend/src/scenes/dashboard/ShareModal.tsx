import React, { useState } from 'react'
import { Modal, Switch, Button } from 'antd'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInput } from 'lib/components/CopyToClipboard'

export function ShareModal({ logic, onCancel }) {
    const { dashboard } = useValues(logic)
    const { setIsSharedDashboard } = useActions(logic)
    const [isShared, setIsShared] = useState(dashboard.is_shared)
    const url = window.location.origin
    return (
        <Modal
            visible={true}
            onCancel={onCancel}
            footer={<Button onClick={onCancel}>Close</Button>}
            title="Share your dashboard with people outside of PostHog."
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
                        <CopyToClipboardInput
                            data-attr="share-dashboard-link"
                            value={url + '/shared_dashboard/' + dashboard.share_token}
                            description="link"
                        />
                    )}
                </span>
            ) : (
                'Your dashboard is private.'
            )}
        </Modal>
    )
}
