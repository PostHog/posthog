import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { organizationLogic } from 'scenes/organizationLogic'
import { organizationIntegrationsLogic } from 'scenes/settings/organization/organizationIntegrationsLogic'

import { IntegrationType } from '~/types'

type EnvMapping = {
    production: number | null
    preview: number | null
    development: number | null
}

function DisconnectButton({ integration }: { integration: IntegrationType }): JSX.Element {
    const { deleteOrganizationIntegration } = useActions(organizationIntegrationsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <LemonButton
            type="secondary"
            status="danger"
            onClick={() => deleteOrganizationIntegration(integration.id)}
            icon={<IconTrash />}
            disabledReason={restrictedReason}
        >
            Disconnect
        </LemonButton>
    )
}

export function VercelIntegrationSuffix({ integration }: { integration: IntegrationType }): JSX.Element {
    const accountUrl = integration.config?.account?.url
    const accountName = integration.config?.account?.name
    const isConnectable = integration.config?.type === 'connectable'
    const envMapping: EnvMapping | undefined = integration.config?.environment_mapping

    if (!isConnectable || !envMapping) {
        return (
            <div className="flex gap-2">
                {accountUrl && (
                    <LemonButton
                        type="secondary"
                        to={accountUrl}
                        targetBlank
                        sideIcon={<IconOpenInNew />}
                        tooltip={accountName ? `Open ${accountName} in Vercel` : 'Open in Vercel'}
                    >
                        View in Vercel
                    </LemonButton>
                )}
                <DisconnectButton integration={integration} />
            </div>
        )
    }

    return (
        <div>
            <div className="flex justify-end">
                <DisconnectButton integration={integration} />
            </div>
            <VercelEnvMappingEditor integration={integration} envMapping={envMapping} />
        </div>
    )
}

function VercelEnvMappingEditor({
    integration,
    envMapping,
}: {
    integration: IntegrationType
    envMapping: EnvMapping
}): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const teams = currentOrganization?.teams || []

    const [mapping, setMapping] = useState<EnvMapping>(envMapping)
    const [saving, setSaving] = useState(false)
    const [dirty, setDirty] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        setMapping(envMapping)
        setDirty(false)
    }, [envMapping])

    const handleChange = (env: keyof EnvMapping, value: number | null): void => {
        setMapping((prev) => ({ ...prev, [env]: value }))
        setDirty(true)
    }

    const handleSave = (): void => {
        setSaving(true)
        setError(null)
        fetch(`/api/organizations/@current/integrations/${integration.id}/environment-mapping/`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('posthog_csrftoken') || '',
            },
            body: JSON.stringify({
                production: mapping.production,
                preview: mapping.preview || mapping.production,
                development: mapping.development || mapping.production,
            }),
        })
            .then((res) => {
                if (!res.ok) {
                    throw new Error('Failed to save')
                }
                setDirty(false)
            })
            .catch(() => setError('Failed to save environment mapping'))
            .finally(() => setSaving(false))
    }

    const teamOptions = teams.map((t) => ({
        value: t.id,
        label: t.name,
    }))

    return (
        <div className="space-y-2 w-full mt-2">
            <h4 className="font-semibold text-sm">Environment mapping</h4>
            {(['production', 'preview', 'development'] as const).map((env) => (
                <div key={env} className="flex items-center gap-2">
                    <span className="text-xs font-medium text-muted uppercase w-24">{env}</span>
                    <LemonSelect
                        size="small"
                        fullWidth
                        value={mapping[env]}
                        onChange={(value) => handleChange(env, value)}
                        options={teamOptions}
                    />
                </div>
            ))}
            {error && <p className="text-danger text-xs">{error}</p>}
            {dirty && (
                <LemonButton type="primary" size="small" loading={saving} onClick={handleSave}>
                    Save mapping
                </LemonButton>
            )}
        </div>
    )
}
