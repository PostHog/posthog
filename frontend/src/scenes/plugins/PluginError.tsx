import { Button, Popover, Tag } from 'antd'
import moment from 'moment'
import React from 'react'
import { ClearOutlined } from '@ant-design/icons'
import { PluginErrorType } from '~/types'

function CodeBlock({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <code
            style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                display: 'block',
                marginTop: 15,
                fontSize: 10,
                maxWidth: 400,
            }}
        >
            {children}
        </code>
    )
}

export function PluginError({ error, reset }: { error: PluginErrorType; reset?: () => void }): JSX.Element | null {
    if (!error) {
        return null
    }
    return (
        <Popover
            title={<div style={{ textAlign: 'center' }}>{moment(error.time).format('YYYY-MM-DD - HH:mm:SS')}</div>}
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
                    {error.stack ? <CodeBlock>{error.stack}</CodeBlock> : null}
                    {error.event ? <CodeBlock>{JSON.stringify(error.event, null, 2)}</CodeBlock> : null}
                </>
            }
            trigger="click"
            placement="bottom"
        >
            <Tag color="red" style={{ position: 'absolute', top: 10, right: 0, cursor: 'pointer' }}>
                ERROR
            </Tag>
        </Popover>
    )
}
