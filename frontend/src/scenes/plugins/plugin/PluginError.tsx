import { PluginErrorType } from '~/types'
import { Tag } from 'antd'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'
import { TZLabel } from '@posthog/apps-common'
import { IconClose } from 'lib/lemon-ui/icons'

export function PluginError({ error, reset }: { error: PluginErrorType; reset?: () => void }): JSX.Element | null {
    if (!error) {
        return null
    }
    return (
        <LemonDropdown
            overlay={
                <>
                    <div className="flex items-center">
                        <span className="grow mr-2">
                            {error.name ? <strong>{error.name} </strong> : ''}
                            <TZLabel time={error.time} />
                        </span>
                        {reset ? (
                            <LemonButton size="small" type="secondary" onClick={reset} icon={<IconClose />}>
                                Clear
                            </LemonButton>
                        ) : null}
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
