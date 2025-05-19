import { LemonInput, Link } from '@posthog/lemon-ui'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonFormDialogProps } from 'lib/lemon-ui/LemonDialog/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ReactNode } from 'react'

interface IntegrationSetupModalProps {
    integration: string
    integrationName: string
    onComplete?: (integrationId: number) => void
}

type IntegrationCredentials = Partial<
    Record<
        string,
        {
            fields: Array<{
                key: string
                label: string
                type: 'password' | 'text'
                required: boolean
            }>
            helpText?: ReactNode
            createFn: (credentials: Record<string, string>, callback: (integration: any) => void) => void
        }
    >
>

const INTEGRATION_CREDENTIALS: IntegrationCredentials = {
    email: {
        fields: [
            { key: 'apiKey', label: 'API key', type: 'text', required: true },
            { key: 'secretKey', label: 'Secret key', type: 'password', required: true },
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

export const getIntegrationSetupModalProps = ({
    integration,
    integrationName,
    onComplete,
}: IntegrationSetupModalProps): LemonFormDialogProps | null => {
    const integrationConfig = INTEGRATION_CREDENTIALS[integration]

    if (!integrationConfig) {
        return null
    }

    return {
        title: `Configure ${integrationName} integration`,
        description: integrationConfig.helpText,
        width: '30rem',
        initialValues: integrationConfig.fields.reduce((acc, field) => ({ ...acc, [field.key]: '' }), {}),
        errors: integrationConfig.fields.reduce(
            (acc, field) => ({
                ...acc,
                [field.key]: (value: string) => {
                    if (field.required && !value) {
                        return `${field.label} is required`
                    }
                },
            }),
            {}
        ),
        content: (isLoading: boolean) => (
            <div className="space-y-4">
                {integrationConfig.fields.map((field) => (
                    <LemonField key={field.key} name={field.key} label={field.label}>
                        <LemonInput type={field.type} disabled={isLoading} />
                    </LemonField>
                ))}
            </div>
        ),
        onSubmit: (values: Record<string, string>) => {
            integrationConfig.createFn(values, (integration) => {
                onComplete?.(integration.id)
            })
        },
    }
}
