import posthog from 'posthog-js'

import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
} from '@posthog/quill'

import type { WarehouseTrinoConnectionApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { buildConnectSnippets } from './connectSnippets'
import { WarehouseCopyButton } from './WarehouseCopyButton'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseConnectSnippets({
    connection,
    schemaName,
}: {
    connection: WarehouseTrinoConnectionApi
    schemaName: string | null
}): JSX.Element {
    const snippets = buildConnectSnippets(connection, schemaName)

    return (
        <Card>
            <CardHeader>
                <CardTitle>Connect a tool</CardTitle>
            </CardHeader>
            <CardContent>
                <Tabs
                    defaultValue={snippets[0].key}
                    onValueChange={(value) => posthog.capture('warehouse connect tab selected', { tab: value })}
                >
                    <div className="max-w-full overflow-x-auto">
                        <TabsList variant="line">
                            {snippets.map((snippet) => (
                                <TabsTrigger
                                    key={snippet.key}
                                    value={snippet.key}
                                    data-attr={`warehouse-connect-tab-${snippet.key}`}
                                >
                                    {snippet.label}
                                </TabsTrigger>
                            ))}
                        </TabsList>
                    </div>
                    {snippets.map((snippet) => (
                        <TabsContent key={snippet.key} value={snippet.key} className="flex flex-col gap-2">
                            <Text size="sm" variant="muted">
                                {snippet.hint}
                            </Text>
                            <pre className="m-0 max-w-full overflow-x-auto rounded-md border p-3 font-mono text-xs">
                                <code>{snippet.code}</code>
                            </pre>
                            <div>
                                <WarehouseCopyButton
                                    value={snippet.code}
                                    thing={`${snippet.label} snippet`}
                                    target={snippet.key}
                                />
                            </div>
                        </TabsContent>
                    ))}
                </Tabs>
            </CardContent>
        </Card>
    )
}
