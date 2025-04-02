import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ReactNode, useState } from 'react'

import { IntegrationKind } from '~/types'

interface IntegrationSetupModalProps {
    isOpen: boolean
    onClose: () => void
    integration: IntegrationKind
    integrationName: string
    onComplete?: (integrationId: number) => void
}

type IntegrationCredentials = Partial<
    Record<
        IntegrationKind,
        {
            fields: Array<{
                key: string
                label: string
                type: 'password' | 'text'
            }>
            helpText?: ReactNode
            createFn: (credentials: Record<string, string>, callback: (integration: any) => void) => void
        }
    >
>

const INTEGRATION_CREDENTIALS: IntegrationCredentials = {
    email: {
        fields: [
            { key: 'apiKey', label: 'API Key', type: 'text' },
            { key: 'secretKey', label: 'Secret Key', type: 'password' },
        ],
        helpText: (
            <>
                Log in or sign up for Mailjet and get your API key and secret key on the{' '}
                <Link to="https://app.mailjet.com/account/apikeys" target="_blank">
                    API Key Management
                </Link>{' '}
                page
            </>
        ),
        createFn: (credentials, callback) => {
            return integrationsLogic.actions.newMailjetKey(credentials.apiKey, credentials.secretKey, callback)
        },
    },
    // Add other input-based integrations here as needed
}

export function IntegrationSetupModal({
    isOpen,
    onClose,
    integration,
    integrationName,
    onComplete,
}: IntegrationSetupModalProps): JSX.Element {
    const [credentials, setCredentials] = useState<Record<string, string>>({})
    const integrationConfig = INTEGRATION_CREDENTIALS[integration]

    const handleSubmit = (): void => {
        if (!integrationConfig) {
            return
        }
        integrationConfig.createFn(credentials, (integration) => {
            onComplete?.(integration.id)
            onClose()
        })
    }

    if (!integrationConfig) {
        return <></>
    }

    return (
        <LemonModal
            title={`Configure ${integrationName} integration`}
            isOpen={isOpen}
            onClose={onClose}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSubmit}>
                        Save
                    </LemonButton>
                </>
            }
            maxWidth="30rem"
        >
            <div className="space-y-4">
                {integrationConfig.helpText && (
                    <div className="text-sm text-gray-500">{integrationConfig.helpText}</div>
                )}
                {integrationConfig.fields.map((field) => (
                    <LemonField key={field.key} label={field.label} name={field.key}>
                        <LemonInput
                            type={field.type}
                            value={credentials[field.key] || ''}
                            onChange={(value) => setCredentials((prev) => ({ ...prev, [field.key]: value }))}
                        />
                    </LemonField>
                ))}
            </div>
        </LemonModal>
    )
}
