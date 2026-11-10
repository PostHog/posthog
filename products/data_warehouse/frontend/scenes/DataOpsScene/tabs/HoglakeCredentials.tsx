import { useActions, useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import type {
    HoglakeConnectApi,
    HoglakeCredentialApi,
    HoglakeCredentialIssuedApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { hoglakeCredentialsLogic } from './hoglakeCredentialsLogic'

// Mirrors HoglakeCredentialCreateRequestSerializer.name in
// products/data_warehouse/backend/presentation/views/data_warehouse.py.
export const CREDENTIAL_NAME_REGEX = /^[A-Za-z0-9][A-Za-z0-9 ._:@/-]{0,63}$/

function tokenCommand(connect: HoglakeConnectApi, clientId: string): string | null {
    if (!connect.token_url) {
        return null
    }
    return [
        `curl -s ${connect.token_url} \\`,
        `  -d grant_type=client_credentials -d audience=hoglake \\`,
        `  -d client_id=${clientId} -d client_secret="$HOGLAKE_CLIENT_SECRET"`,
    ].join('\n')
}

export function IssuedCredentialBanner({
    issued,
    connect,
    onClose,
}: {
    issued: HoglakeCredentialIssuedApi | null
    connect: HoglakeConnectApi | null | undefined
    onClose: () => void
}): JSX.Element | null {
    if (!issued) {
        return null
    }
    const command = connect ? tokenCommand(connect, issued.client_id) : null
    return (
        <LemonBanner type="warning" onClose={onClose}>
            <div className="space-y-2">
                <strong>Save this secret now — it won't be shown again.</strong>
                <div>
                    <LemonLabel>Client ID</LemonLabel>
                    <CodeSnippet compact thing="client ID">
                        {issued.client_id}
                    </CodeSnippet>
                </div>
                <div>
                    <LemonLabel>Client secret</LemonLabel>
                    <CodeSnippet compact thing="client secret">
                        {issued.client_secret}
                    </CodeSnippet>
                </div>
                {command && (
                    <div>
                        <LemonLabel>Get a token</LemonLabel>
                        <CodeSnippet language={Language.Bash} thing="token command">
                            {command}
                        </CodeSnippet>
                    </div>
                )}
            </div>
        </LemonBanner>
    )
}

export function ConnectDetails({ connect }: { connect: HoglakeConnectApi }): JSX.Element {
    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-3 @lg:grid-cols-2">
                <div>
                    <LemonLabel>Catalog</LemonLabel>
                    <CodeSnippet compact thing="catalog">
                        {connect.catalog}
                    </CodeSnippet>
                </div>
                {connect.hoglake_url && (
                    <div>
                        <LemonLabel>Hoglake URL</LemonLabel>
                        <CodeSnippet compact thing="hoglake URL">
                            {connect.hoglake_url}
                        </CodeSnippet>
                    </div>
                )}
                {connect.token_url && (
                    <div className="@lg:col-span-2">
                        <LemonLabel>Token URL</LemonLabel>
                        <CodeSnippet compact thing="token URL">
                            {connect.token_url}
                        </CodeSnippet>
                    </div>
                )}
            </div>
        </div>
    )
}

export function HoglakeCredentials(): JSX.Element | null {
    const {
        hoglakeCredentials,
        hoglakeCredentialsLoading,
        issuedCredential,
        isSubmitting,
        newCredentialName,
        newCredentialScope,
    } = useValues(hoglakeCredentialsLogic)
    const {
        createCredential,
        rotateCredential,
        revokeCredential,
        setIssuedCredential,
        setNewCredentialName,
        setNewCredentialScope,
    } = useActions(hoglakeCredentialsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    // Only org admins can list them; for everyone else the section stays hidden.
    if (adminRestrictionReason || (!hoglakeCredentials && !hoglakeCredentialsLoading)) {
        return null
    }

    const live = (hoglakeCredentials?.hoglake_credentials ?? []).filter((c) => !c.revoked_at)
    const nameError =
        newCredentialName && !CREDENTIAL_NAME_REGEX.test(newCredentialName)
            ? 'Letters, digits, spaces and ._:@/- only; at most 64 characters'
            : null

    return (
        <div className="border rounded p-4 space-y-3">
            <div>
                <h3 className="mb-1">Hoglake credentials</h3>
                <p className="text-muted text-xs mb-0">
                    OAuth client credentials for reading this organization's hoglake catalog directly, e.g. from Spark,
                    DuckDB or PyIceberg. Exchange one for a short-lived token at the token URL. Members' personal
                    credentials are listed too: you can revoke them, and only their owners can rotate them.
                </p>
            </div>

            <IssuedCredentialBanner
                issued={issuedCredential}
                connect={hoglakeCredentials?.connect}
                onClose={() => setIssuedCredential(null)}
            />

            {hoglakeCredentials?.connect && <ConnectDetails connect={hoglakeCredentials.connect} />}

            <LemonTable<HoglakeCredentialApi>
                dataSource={live}
                loading={hoglakeCredentialsLoading}
                rowKey="client_id"
                size="small"
                emptyState="No hoglake credentials yet"
                columns={[
                    { title: 'Name', dataIndex: 'name' },
                    {
                        title: 'Owner',
                        key: 'owner',
                        render: (_, c) =>
                            c.kind === 'team' ? (
                                <span className="flex items-center gap-1">
                                    <LemonTag type="muted">Personal</LemonTag>
                                    {c.owner_name || c.owner_email || 'Former member'}
                                </span>
                            ) : (
                                'Organization'
                            ),
                    },
                    {
                        title: 'Client ID',
                        dataIndex: 'client_id',
                        render: (_, c) => <span className="font-mono text-xs">{c.client_id}</span>,
                    },
                    {
                        title: 'Access',
                        dataIndex: 'scope',
                        render: (_, c) => (
                            <LemonTag type={c.scope === 'write' ? 'warning' : 'default'}>{c.scope}</LemonTag>
                        ),
                    },
                    {
                        title: 'Secret rotated',
                        dataIndex: 'last_rotated_at',
                        render: (_, c) => <TZLabel time={c.last_rotated_at} />,
                    },
                    { title: 'Expires', dataIndex: 'expires_at', render: (_, c) => <TZLabel time={c.expires_at} /> },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, c) => (
                            <div className="flex gap-1">
                                {/* A personal credential's secret is its owner's alone: admins can only revoke it. */}
                                {c.kind !== 'team' && (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        disabledReason={isSubmitting ? 'Working…' : undefined}
                                        onClick={() =>
                                            LemonDialog.open({
                                                title: `Rotate the secret for "${c.name}"?`,
                                                description:
                                                    'The current secret stops working immediately. Clients need the new one to get tokens.',
                                                primaryButton: {
                                                    children: 'Rotate secret',
                                                    onClick: () => rotateCredential(c.client_id),
                                                },
                                                secondaryButton: { children: 'Cancel' },
                                            })
                                        }
                                    >
                                        Rotate
                                    </LemonButton>
                                )}
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    status="danger"
                                    disabledReason={isSubmitting ? 'Working…' : undefined}
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: `Revoke "${c.name}"?`,
                                            description:
                                                c.kind === 'team'
                                                    ? `This is ${c.owner_name || c.owner_email || 'a former member'}'s personal credential. New tokens are refused and its S3 access stops now. This cannot be undone.`
                                                    : 'New tokens are refused and its S3 access stops now. This cannot be undone.',
                                            primaryButton: {
                                                children: 'Revoke',
                                                status: 'danger',
                                                onClick: () => revokeCredential(c.client_id),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }
                                >
                                    Revoke
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
            />

            <div className="flex flex-wrap items-end gap-2">
                <div className="flex-1 min-w-40">
                    <LemonLabel>New credential name</LemonLabel>
                    <LemonInput
                        value={newCredentialName}
                        onChange={setNewCredentialName}
                        placeholder="e.g. laptop or airflow"
                        maxLength={64}
                        status={nameError ? 'danger' : 'default'}
                    />
                </div>
                <LemonSegmentedButton
                    value={newCredentialScope}
                    onChange={setNewCredentialScope}
                    options={[
                        { value: 'read', label: 'Read' },
                        { value: 'write', label: 'Read & write' },
                    ]}
                />
                <LemonButton
                    type="primary"
                    disabledReason={
                        !newCredentialName
                            ? 'Name the credential'
                            : nameError
                              ? nameError
                              : isSubmitting
                                ? 'Working…'
                                : undefined
                    }
                    onClick={() => createCredential({ name: newCredentialName, scope: newCredentialScope })}
                >
                    Create credential
                </LemonButton>
            </div>
        </div>
    )
}
