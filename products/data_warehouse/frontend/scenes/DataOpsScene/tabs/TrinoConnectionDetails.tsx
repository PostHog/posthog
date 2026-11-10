import posthog from 'posthog-js'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import type { WarehouseTrinoConnectionApi } from 'products/data_warehouse/frontend/generated/api.schemas'

export function TrinoConnectionDetails({
    connection,
    schemaName,
}: {
    connection: WarehouseTrinoConnectionApi
    schemaName: string | null
}): JSX.Element {
    const { host, port, catalog, username } = connection
    const cliCommand =
        `trino --server https://${host}:${port} --user ${username} --password --catalog ${catalog}` +
        (schemaName ? ` --schema ${schemaName}` : '')

    return (
        <div className="border rounded p-4 space-y-3">
            <h3 className="mb-2">Connection details</h3>
            <div className="@container">
                <div className="grid grid-cols-1 gap-3 @lg:grid-cols-2">
                    <div>
                        <LemonLabel>Host</LemonLabel>
                        <CodeSnippet compact thing="host">
                            {host}
                        </CodeSnippet>
                    </div>
                    <div>
                        <LemonLabel>Port</LemonLabel>
                        <CodeSnippet compact thing="port">
                            {String(port)}
                        </CodeSnippet>
                    </div>
                    <div>
                        <LemonLabel>Catalog</LemonLabel>
                        <CodeSnippet compact thing="catalog">
                            {catalog}
                        </CodeSnippet>
                    </div>
                    {schemaName && (
                        <div>
                            <LemonLabel>Schema</LemonLabel>
                            <CodeSnippet compact thing="schema">
                                {schemaName}
                            </CodeSnippet>
                        </div>
                    )}
                    <div>
                        <LemonLabel>Username</LemonLabel>
                        <CodeSnippet compact thing="username">
                            {username}
                        </CodeSnippet>
                    </div>
                </div>
            </div>
            <div>
                <LemonLabel>Connect with the Trino CLI</LemonLabel>
                <CodeSnippet
                    compact
                    wrap
                    thing="Trino CLI command"
                    onCopy={() =>
                        posthog.capture('managed warehouse connection details copied', { connection_type: 'trino_cli' })
                    }
                >
                    {cliCommand}
                </CodeSnippet>
            </div>
            <p className="text-muted text-xs mb-0">
                The password is shown only once, when you provision the warehouse. If you didn't save it, use "Reset
                password" below to generate a new one.
            </p>
        </div>
    )
}
