import React from 'react'
import { Alert, Space, Button } from 'antd'

export function CloudAnnouncement({ message }: { message: string }): JSX.Element | null {
    const parsed_message = message.split('_').join(' ');
    const github_issue_regex = /ph-([0-9]{1,8})/ig;
    const github_issue_ids = github_issue_regex.exec(message);
    return (
        <div style={{ marginTop: 15 }}>
            <Alert 
                message={parsed_message.replace(github_issue_regex, '')} 
                    action={
                        github_issue_ids ? (
                        <Space>
                            <Button size="small" type="ghost" href={'https://github.com/PostHog/posthog/issues/' + github_issue_ids[1]} target='_blank'>
                                More details
                            </Button>
                        </Space>
                        ): null
                    }
            type="warning" showIcon closable />
        </div>
    )
}
