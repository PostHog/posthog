import { useActions, useValues } from 'kea'

import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { Badge, Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { urls } from 'scenes/urls'

import type { KnowledgeKeyApi } from '../../generated/api.schemas'
import { connectAgentLogic } from './connectAgentLogic'
import { QuillRetryText } from './QuillRetryText'

function KeyReads({ apiKey }: { apiKey: KnowledgeKeyApi }): JSX.Element {
    const { libraryNames } = useValues(connectAgentLogic)
    const todayRailNav = useQuillSurface()

    if (!apiKey.is_limited) {
        return <>All business knowledge</>
    }
    if (!apiKey.library_id) {
        return todayRailNav ? (
            <Badge variant="warning">Nothing, its library was deleted</Badge>
        ) : (
            <LemonTag type="warning">Nothing, its library was deleted</LemonTag>
        )
    }
    return <>{libraryNames[apiKey.library_id] ?? 'One library'}</>
}

export function ConnectAgentKeysTable(): JSX.Element | null {
    const { listedKeys: keys, keysLoading, fixedLibraryId } = useValues(connectAgentLogic)
    const { loadKeys } = useActions(connectAgentLogic)
    const todayRailNav = useQuillSurface()

    if (!keys && todayRailNav) {
        return keysLoading ? null : <QuillRetryText message="Couldn't load the keys." onRetry={() => loadKeys()} />
    }
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

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Table size="sm" fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Key</TableHead>
                            <TableHead>Value</TableHead>
                            {!fixedLibraryId && <TableHead expand>Reads</TableHead>}
                            <TableHead>Last used</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {keys.map((apiKey) => (
                            <TableRow key={apiKey.id}>
                                <TableCell>{apiKey.label}</TableCell>
                                <TableCell>
                                    <code>{apiKey.mask_value}</code>
                                </TableCell>
                                {!fixedLibraryId && (
                                    <TableCell expand>
                                        <KeyReads apiKey={apiKey} />
                                    </TableCell>
                                )}
                                <TableCell>
                                    {apiKey.last_used_at ? <TZLabel time={apiKey.last_used_at} /> : 'Never'}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Roll or delete a key in{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.settings('environment-secret-api-keys')} />}
                    >
                        project secret API keys
                    </Button>
                    .
                </Text>
            </div>
        )
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
                    // On a library page every listed key reads that library.
                    ...(fixedLibraryId
                        ? []
                        : [
                              {
                                  title: 'Reads',
                                  render: (_: unknown, apiKey: KnowledgeKeyApi) => <KeyReads apiKey={apiKey} />,
                              },
                          ]),
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
