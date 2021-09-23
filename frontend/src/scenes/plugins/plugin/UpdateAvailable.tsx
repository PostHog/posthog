import { CloudDownloadOutlined } from '@ant-design/icons'
import { Tag } from 'antd'
import React from 'react'
import { Tooltip } from 'lib/components/Tooltip'

function SHATag({ tag }: { tag: string }): JSX.Element {
    // github/gitlab sha tag
    if (tag.match(/^[a-f0-9]{40}$/)) {
        return <code>{tag.substring(0, 7)}</code>
    }
    return <code>{tag}</code>
}

export function UpdateAvailable({ url, tag, latestTag }: { url: string; tag: string; latestTag: string }): JSX.Element {
    let compareUrl: string = ''

    if (url.match(/^https:\/\/(www.|)github.com\//)) {
        compareUrl = `${url}/compare/${tag}...${latestTag}`
    }
    if (url.match(/^https:\/\/(www.|)gitlab.com\//)) {
        compareUrl = `${url}/-/compare/${tag}...${latestTag}`
    }

    return (
        <Tooltip
            title={
                <div>
                    Installed: <SHATag tag={tag} />
                    <br />
                    Latest: <SHATag tag={latestTag} />
                    {compareUrl ? <div style={{ marginTop: 10 }}>Click to see the diff</div> : null}
                </div>
            }
        >
            {compareUrl ? (
                <a href={compareUrl} target="_blank" rel="noreferrer noopener">
                    <Tag color="volcano" style={{ cursor: 'pointer' }}>
                        <CloudDownloadOutlined /> Update available!
                    </Tag>
                </a>
            ) : (
                <Tag color="volcano">
                    <CloudDownloadOutlined /> Update available!
                </Tag>
            )}
        </Tooltip>
    )
}
