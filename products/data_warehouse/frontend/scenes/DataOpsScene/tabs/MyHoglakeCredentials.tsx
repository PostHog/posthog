import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import type { HoglakeCredentialApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { CREDENTIAL_NAME_REGEX, ConnectDetails, IssuedCredentialBanner } from './HoglakeCredentials'
import { myHoglakeCredentialsLogic } from './myHoglakeCredentialsLogic'

export function MyHoglakeCredentials(): JSX.Element | null {
    const {
        myHoglakeCredentials,
        myHoglakeCredentialsLoading,
        issuedCredential,
        isSubmitting,
        newCredentialName,
        newCredentialScope,
        projects,
        effectiveTeamIds,
    } = useValues(myHoglakeCredentialsLogic)
    const {
        createCredential,
        rotateCredential,
        revokeCredential,
        setIssuedCredential,
        setNewCredentialName,
        setNewCredentialScope,
        setSelectedTeamIds,
    } = useActions(myHoglakeCredentialsLogic)

    // Off in this region, or no access to this project's warehouse: nothing to show.
    if (!myHoglakeCredentials && !myHoglakeCredentialsLoading) {
        return null
    }

    const projectName = new Map(projects.map((p) => [p.id, p.name]))
    const live = (myHoglakeCredentials?.hoglake_credentials ?? []).filter((c) => !c.revoked_at)
    const nameError =
        newCredentialName && !CREDENTIAL_NAME_REGEX.test(newCredentialName)
            ? 'Letters, digits, spaces and ._:@/- only; at most 64 characters'
            : null

    return (
        <div className="border rounded p-4 space-y-3">
            <div>
                <h3 className="mb-1 flex items-center gap-2">
                    Your hoglake credentials <LemonTag type="highlight">Preview</LemonTag>
                </h3>
                <p className="text-muted text-xs mb-1">
                    Your own OAuth client credentials for this organization's hoglake catalog. Each reaches only the
                    projects you choose, with the access you have on them now: if you lose access to a project, its next
                    token leaves it out.
                </p>
                <p className="text-muted text-xs mb-0">
                    For now these reach only the catalog metadata of your projects' namespaces. Reading table data needs
                    S3 access, which personal credentials don't get yet.
                </p>
            </div>

            <IssuedCredentialBanner
                issued={issuedCredential}
                connect={myHoglakeCredentials?.connect}
                onClose={() => setIssuedCredential(null)}
            />

            {myHoglakeCredentials?.connect && <ConnectDetails connect={myHoglakeCredentials.connect} />}

            <LemonTable<HoglakeCredentialApi>
                dataSource={live}
                loading={myHoglakeCredentialsLoading}
                rowKey="client_id"
                size="small"
                emptyState="You have no hoglake credentials yet"
                columns={[
                    { title: 'Name', dataIndex: 'name' },
                    {
                        title: 'Client ID',
                        dataIndex: 'client_id',
                        render: (_, c) => <span className="font-mono text-xs">{c.client_id}</span>,
                    },
                    {
                        title: 'Projects',
                        key: 'projects',
                        render: (_, c) => (
                            <span className="flex flex-wrap gap-1">
                                {(c.team_ids ?? []).map((id) => (
                                    // A project no longer listed is one you can't see now: its tokens leave it out.
                                    <LemonTag key={id} type={projectName.has(id) ? 'default' : 'muted'}>
                                        {projectName.get(id) ?? `Project ${id} (no access)`}
                                    </LemonTag>
                                ))}
                            </span>
                        ),
                    },
                    {
                        title: 'Access',
                        dataIndex: 'scope',
                        render: (_, c) => (
                            <LemonTag type={c.scope === 'write' ? 'warning' : 'default'}>{c.scope}</LemonTag>
                        ),
                    },
                    { title: 'Expires', dataIndex: 'expires_at', render: (_, c) => <TZLabel time={c.expires_at} /> },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, c) => (
                            <div className="flex gap-1">
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
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    status="danger"
                                    disabledReason={isSubmitting ? 'Working…' : undefined}
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: `Revoke "${c.name}"?`,
                                            description:
                                                'New tokens are refused and its S3 access stops now. This cannot be undone.',
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

            <div className="space-y-2">
                <div>
                    <LemonLabel>Projects</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        placeholder="Choose the projects this credential reaches"
                        value={effectiveTeamIds.map(String)}
                        onChange={(values: string[]) => setSelectedTeamIds(values.map(Number))}
                        options={projects.map((p) => ({
                            key: String(p.id),
                            label: p.access === 'write' ? p.name : `${p.name} (read only)`,
                        }))}
                    />
                </div>
                <div className="flex flex-wrap items-end gap-2">
                    <div className="flex-1 min-w-40">
                        <LemonLabel>New credential name</LemonLabel>
                        <LemonInput
                            value={newCredentialName}
                            onChange={setNewCredentialName}
                            placeholder="e.g. laptop or notebook"
                            maxLength={64}
                            status={nameError ? 'danger' : 'default'}
                        />
                    </div>
                    <LemonSegmentedButton
                        value={newCredentialScope}
                        onChange={setNewCredentialScope}
                        options={[
                            { value: 'read', label: 'Read' },
                            {
                                value: 'write',
                                label: 'Read & write',
                                tooltip: 'Write applies only to projects where you can edit warehouse objects',
                            },
                        ]}
                    />
                    <LemonButton
                        type="primary"
                        disabledReason={
                            !newCredentialName
                                ? 'Name the credential'
                                : nameError
                                  ? nameError
                                  : effectiveTeamIds.length === 0
                                    ? 'Choose at least one project'
                                    : isSubmitting
                                      ? 'Working…'
                                      : undefined
                        }
                        onClick={() =>
                            createCredential({
                                name: newCredentialName,
                                scope: newCredentialScope,
                                teamIds: effectiveTeamIds,
                            })
                        }
                    >
                        Create credential
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
