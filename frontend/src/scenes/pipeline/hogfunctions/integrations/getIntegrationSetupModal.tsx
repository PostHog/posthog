import { LemonInput, LemonSwitch, Link } from '@posthog/lemon-ui'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonFormDialogProps } from 'lib/lemon-ui/LemonDialog/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ReactNode } from 'react'

type IntegrationVendor = 'Mailjet' | 'Resend'

type FieldType = 'password' | 'text' | 'number' | 'boolean'

type IntegrationField = {
    key: string
    label: string
    type: FieldType
    required: boolean
}

type IntegrationCredentials = Partial<{
    Mailjet: {
        fields: IntegrationField[]
        helpText?: ReactNode
        createFn: (credentials: MailjetCredentials, callback: (integration: { id: number }) => void) => void
    }
    Resend: {
        fields: IntegrationField[]
        helpText?: ReactNode
        createFn: (credentials: ResendCredentials, callback: (integration: { id: number }) => void) => void
    }
}>

type MailjetCredentials = {
    apiKey: string
    secretKey: string
}

type ResendCredentials = {
    secretKey: string
}

const INTEGRATION_CREDENTIALS: IntegrationCredentials = {
    Mailjet: {
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
        createFn: (credentials: MailjetCredentials, callback) => {
            return integrationsLogic.actions.newMailjetKey(credentials.apiKey, credentials.secretKey, callback)
        },
    },
    Resend: {
        fields: [{ key: 'secretKey', label: 'Secret key', type: 'password', required: true }],
        helpText: (
            <>
                Get your Resend API key from the{' '}
                <Link to="https://resend.com/api-keys" target="_blank">
                    API Keys
                </Link>{' '}
                page
            </>
        ),
        createFn: (credentials: ResendCredentials, callback) => {
            return integrationsLogic.actions.newResendKey(credentials.secretKey, callback)
        },
    },
    // Add other input-based integrations here as needed
}

export const getIntegrationSetupModalProps = ({
    onComplete,
    vendor,
}: {
    onComplete: (integrationId: number) => void
    vendor: IntegrationVendor
}): LemonFormDialogProps | null => {
    const integrationConfig = INTEGRATION_CREDENTIALS[vendor]

    if (!integrationConfig) {
        return null
    }

    return {
        title: `Configure ${vendor} integration`,
        description: integrationConfig.helpText,
        width: '30rem',
        initialValues: integrationConfig.fields.reduce<Record<string, string | number | boolean>>(
            (acc, field) => ({ ...acc, [field.key]: '' }),
            {}
        ),
        errors: integrationConfig.fields.reduce<Record<string, (value: string) => string | undefined>>(
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
                        {({ value, onChange }) =>
                            field.type === 'boolean' ? (
                                <LemonSwitch checked={Boolean(value)} onChange={onChange} disabled={isLoading} />
                            ) : (
                                <LemonInput type={field.type} value={value} onChange={onChange} disabled={isLoading} />
                            )
                        }
                    </LemonField>
                ))}
            </div>
        ),
        onSubmit: (values: Record<string, string | number | boolean>) => {
            integrationConfig.createFn(values as any, (integration) => {
                onComplete?.(integration.id)
            })
        },
    }
}
