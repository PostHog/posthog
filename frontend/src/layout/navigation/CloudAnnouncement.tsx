import React from 'react'
import { Alert, Space, Button } from 'antd'

export function CloudAnnouncement({ message }: { message: string }): JSX.Element | null {
    const parsedMessage = message.split('_').join(' ')
    const githubIssueIds = message.match(/ph-([0-9]{1,8})/i)
    return (
        <div style={{ marginTop: 15 }}>
            <Alert
                message={parsedMessage.replace(/ph-[0-9]{1,8}/gi, '')}
                action={
                    githubIssueIds ? (
                        <Space>
                            <Button
                                size="small"
                                type="ghost"
                                href={'https://github.com/PostHog/posthog/issues/' + githubIssueIds[1]}
                                target="_blank"
                            >
                                More details
                            </Button>
                        </Space>
                    ) : null
                }
                type="warning"
                showIcon
                closable
            />
        </div>
    )
}
