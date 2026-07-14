import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { snowflakeSetupModalLogicType } from './snowflakeSetupModalLogicType'

export interface SnowflakeSetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export const snowflakeSetupModalLogic = kea<snowflakeSetupModalLogicType>([
    path(['integrations', 'snowflake', 'snowflakeSetupModalLogic']),
    props({} as SnowflakeSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        snowflakeIntegration: {
            defaults: {
                name: '',
                account: '',
                user: '',
                authentication_type: 'keypair',
                password: '',
                private_key: '',
                private_key_passphrase: '',
            },
            errors: ({ name, account, user, authentication_type, password, private_key }) => ({
                name: name.trim() ? undefined : 'Name is required',
                account: account.trim() ? undefined : 'Account is required',
                user: user.trim() ? undefined : 'User is required',
                password: authentication_type === 'password' && !password.trim() ? 'Password is required' : undefined,
                private_key:
                    authentication_type === 'keypair' && !private_key.trim() ? 'Private key is required' : undefined,
            }),
            submit: async () => {
                const { snowflakeIntegration } = values
                try {
                    const integration = await api.integrations.create({
                        kind: 'snowflake',
                        config: {
                            name: snowflakeIntegration.name,
                            account: snowflakeIntegration.account,
                            user: snowflakeIntegration.user,
                            authentication_type: snowflakeIntegration.authentication_type,
                            password: snowflakeIntegration.password,
                            private_key: snowflakeIntegration.private_key,
                            private_key_passphrase: snowflakeIntegration.private_key_passphrase,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Snowflake connection created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create Snowflake connection')
                    throw error
                }
            },
        },
    })),
])
