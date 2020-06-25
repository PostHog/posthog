import React, { useState } from 'react'
import { Modal, Switch, Button } from 'antd'
import { useActions, useValues } from 'kea'
import { CopyToClipboard } from 'lib/components/CopyToClipboard'

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
                onChange={active => {
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
                        <CopyToClipboard url={url + '/shared_dashboard/' + dashboard.share_token} />
                    )}
                </span>
            ) : (
                'Your dashboard is private.'
            )}
        </Modal>
    )
}
