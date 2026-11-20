import type { WarehouseTrinoConnectionApi } from 'products/data_warehouse/frontend/generated/api.schemas'

export type ConnectSnippetKey = 'trino_cli' | 'python' | 'dbt' | 'metabase' | 'hex'

export interface ConnectSnippet {
    key: ConnectSnippetKey
    label: string
    // What to do with the code, shown above it.
    hint: string
    code: string
}

export const PASSWORD_PLACEHOLDER = '<your password>'
export const PASSWORD_ENV_VAR = 'TRINO_PASSWORD'

/** Snippets for each client, filled from the live connection. They never hold a secret: the password comes from an environment variable. */
export function buildConnectSnippets(
    connection: Pick<WarehouseTrinoConnectionApi, 'host' | 'port' | 'catalog' | 'username'>,
    schemaName: string | null
): ConnectSnippet[] {
    const { host, port, catalog, username } = connection
    return [
        {
            key: 'trino_cli',
            label: 'Trino CLI',
            hint: 'Run this in a terminal. The CLI asks for your password.',
            code:
                `trino --server https://${host}:${port} --user "${username}" --password --catalog ${catalog}` +
                (schemaName ? ` --schema ${schemaName}` : ''),
        },
        {
            key: 'python',
            label: 'Python',
            hint: `Install the trino package, then set ${PASSWORD_ENV_VAR} in your environment.`,
            code: [
                'import os',
                '',
                'from trino.auth import BasicAuthentication',
                'from trino.dbapi import connect',
                '',
                'conn = connect(',
                `    host="${host}",`,
                `    port=${port},`,
                '    http_scheme="https",',
                `    auth=BasicAuthentication("${username}", os.environ["${PASSWORD_ENV_VAR}"]),`,
                `    catalog="${catalog}",`,
                ...(schemaName ? [`    schema="${schemaName}",`] : []),
                ')',
                'cur = conn.cursor()',
                'cur.execute("SELECT 1")',
                'print(cur.fetchall())',
            ].join('\n'),
        },
        {
            key: 'dbt',
            label: 'dbt',
            hint: `Install dbt-trino, add this to profiles.yml and set ${PASSWORD_ENV_VAR} in your environment.`,
            code: [
                'posthog_warehouse:',
                '  target: dev',
                '  outputs:',
                '    dev:',
                '      type: trino',
                '      method: ldap',
                `      host: ${host}`,
                `      port: ${port}`,
                '      http_scheme: https',
                `      user: "${username}"`,
                `      password: "{{ env_var('${PASSWORD_ENV_VAR}') }}"`,
                `      database: ${catalog}`,
                `      schema: ${schemaName ?? '<your schema>'}`,
                '      threads: 4',
            ].join('\n'),
        },
        {
            key: 'metabase',
            label: 'Metabase',
            hint: 'Add a database in Metabase and choose Starburst (Trino) as the type. Fill in these fields.',
            code: [
                'Display name: PostHog warehouse',
                `Host: ${host}`,
                `Port: ${port}`,
                `Catalog: ${catalog}`,
                ...(schemaName ? [`Schema: ${schemaName}`] : []),
                `Username: ${username}`,
                `Password: ${PASSWORD_PLACEHOLDER}`,
                'Use a secure connection (SSL): on',
            ].join('\n'),
        },
        {
            key: 'hex',
            label: 'Hex',
            hint: 'Add a data connection in Hex and choose Trino as the type. Fill in these fields.',
            code: [
                'Name: PostHog warehouse',
                `Host: ${host}`,
                `Port: ${port}`,
                `Catalog: ${catalog}`,
                ...(schemaName ? [`Schema: ${schemaName}`] : []),
                `Username: ${username}`,
                `Password: ${PASSWORD_PLACEHOLDER}`,
                'Use SSL: on',
            ].join('\n'),
        },
    ]
}
