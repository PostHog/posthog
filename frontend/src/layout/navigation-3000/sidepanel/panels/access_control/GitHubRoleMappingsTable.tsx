import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import type { RoleExternalReferenceApi } from 'products/integrations/frontend/generated/api.schemas'

export function GitHubRoleMappingsTable({
    references,
    canEditRoles,
    onDelete,
}: {
    references: RoleExternalReferenceApi[]
    canEditRoles: boolean | null
    onDelete: (id: string) => void
}): JSX.Element | null {
    if (references.length === 0) {
        return null
    }

    return (
        <LemonTable
            columns={[
                {
                    title: 'Team',
                    key: 'provider_role_name',
                    render: (_, reference: RoleExternalReferenceApi) => reference.provider_role_name,
                },
                {
                    title: 'Slug',
                    key: 'provider_role_slug',
                    render: (_, reference: RoleExternalReferenceApi) => reference.provider_role_slug || '-',
                },
                {
                    key: 'actions',
                    width: 0,
                    render: (_, reference: RoleExternalReferenceApi) => (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            status="danger"
                            disabledReason={!canEditRoles ? 'You cannot edit this' : undefined}
                            onClick={() => onDelete(reference.id)}
                        >
                            Remove
                        </LemonButton>
                    ),
                },
            ]}
            dataSource={references}
            embedded
        />
    )
}
