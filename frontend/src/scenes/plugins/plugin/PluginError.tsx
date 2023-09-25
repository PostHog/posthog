import { Button, Tag } from 'antd'
import { ClearOutlined } from '@ant-design/icons'
import { PluginErrorType } from '~/types'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { LemonDropdown } from '@posthog/lemon-ui'

export function PluginError({ error, reset }: { error: PluginErrorType; reset?: () => void }): JSX.Element | null {
    if (!error) {
        return null
    }
    return (
        <LemonDropdown
            title={<div style={{ textAlign: 'center' }}>{dayjs(error.time).format('YYYY-MM-DD - HH:mm:ss')}</div>}
            overlay={
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
            placement="top"
            showArrow
        >
            <Tag color="red" style={{ cursor: 'pointer' }}>
                ERROR
            </Tag>
        </LemonDropdown>
    )
}
