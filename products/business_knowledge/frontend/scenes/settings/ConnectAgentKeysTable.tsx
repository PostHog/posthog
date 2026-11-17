import { useActions, useValues } from 'kea'

import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { KnowledgeKeyApi } from '../../generated/api.schemas'
import { connectAgentLogic } from './connectAgentLogic'

function KeyReads({ apiKey }: { apiKey: KnowledgeKeyApi }): JSX.Element {
    const { libraryNames } = useValues(connectAgentLogic)

    if (!apiKey.is_limited) {
        return <>All business knowledge</>
    }
    if (!apiKey.library_id) {
        return <LemonTag type="warning">Nothing, its library was deleted</LemonTag>
    }
    return <>{libraryNames[apiKey.library_id] ?? 'One library'}</>
}

export function ConnectAgentKeysTable(): JSX.Element | null {
    const { listedKeys: keys, keysLoading } = useValues(connectAgentLogic)
    const { loadKeys } = useActions(connectAgentLogic)

    if (!keys) {
        return keysLoading ? null : (
            <p className="m-0">
                Couldn't load the keys. <Link onClick={() => loadKeys()}>Try again</Link>
            </p>
        )
    }
    if (keys.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonTable
                size="small"
                dataSource={keys}
                rowKey="id"
                columns={[
                    { title: 'Key', dataIndex: 'label' },
                    {
                        title: 'Value',
                        render: (_, apiKey) => <code>{apiKey.mask_value}</code>,
                    },
                    {
                        title: 'Reads',
                        render: (_, apiKey) => <KeyReads apiKey={apiKey} />,
                    },
                    {
                        title: 'Last used',
                        render: (_, apiKey) => (apiKey.last_used_at ? <TZLabel time={apiKey.last_used_at} /> : 'Never'),
                    },
                ]}
            />
            <p className="m-0 text-xs text-secondary">
                Roll or delete a key in{' '}
                <Link to={urls.settings('environment-secret-api-keys')}>project secret API keys</Link>.
            </p>
        </div>
    )
}
