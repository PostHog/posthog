import { Button, Popover, Tag } from 'antd'
import dayjs from 'dayjs'
import React from 'react'
import { ClearOutlined } from '@ant-design/icons'
import { PluginErrorType } from '~/types'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'

export function PluginError({ error, reset }: { error: PluginErrorType; reset?: () => void }): JSX.Element | null {
    if (!error) {
        return null
    }
    return (
        <Popover
            title={<div style={{ textAlign: 'center' }}>{dayjs(error.time).format('YYYY-MM-DD - HH:mm:ss')}</div>}
            content={
                <>
                    {reset ? (
                        <Button size="small" onClick={reset} style={{ float: 'right', marginLeft: 10 }}>
                            <ClearOutlined /> Delete
                        </Button>
                    ) : null}
                    <div>
                        {error.name ? <strong>{error.name}: </strong> : ''}
                        {error.message}
                    </div>
                    {error.stack ? (
                        <CodeSnippet wrap style={{ fontSize: 10 }} language={Language.JavaScript}>
                            {error.stack}
                        </CodeSnippet>
                    ) : null}
                    {error.event ? (
                        <CodeSnippet wrap style={{ fontSize: 10 }} language={Language.JSON}>
                            {JSON.stringify(error.event, null, 2)}
                        </CodeSnippet>
                    ) : null}
                </>
            }
            trigger="click"
            placement="top"
        >
            <Tag color="red" style={{ cursor: 'pointer' }}>
                ERROR
            </Tag>
        </Popover>
    )
}
