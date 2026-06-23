import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { IntegrationType } from '~/types'

import type { postgreSQLSetupModalLogicType } from './postgreSQLSetupModalLogicType'

export interface PostgreSQLSetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export const postgreSQLSetupModalLogic = kea<postgreSQLSetupModalLogicType>([
    path(['integrations', 'postgreSQL', 'postgreSQLSetupModalLogic']),
    props({} as PostgreSQLSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        postgreSQLIntegration: {
            defaults: {
                host: null as string | null,
                port: 5432,
                user: null as string | null,
                password: null as string | null,
                ssl_mode: 'no',
                use_system_ca: false,
                ssl_root_cert: null as string | null,
            },
            errors: ({ host, port, user, password, ssl_mode, use_system_ca, ssl_root_cert }) => ({
                host: host?.trim() ? undefined : 'Host is required',
                port: port ? undefined : 'Port is required',
                user: user?.trim() ? undefined : 'User is required',
                password: password?.trim() ? undefined : 'Password is required',
                ssl_root_cert:
                    ssl_mode === 'no' || use_system_ca || ssl_root_cert?.trim()
                        ? undefined
                        : 'Upload a root certificate, or use the system certificate authorities',
            }),
            submit: async () => {
                try {
                    const { host, port, user, password, ssl_mode, use_system_ca, ssl_root_cert } =
                        values.postgreSQLIntegration
                    const integration = await api.integrations.create({
                        kind: 'postgresql',
                        config: {
                            host: host,
                            port: port,
                            user: user,
                            password: password,
                            ...(ssl_mode !== 'no' && {
                                ssl_mode: ssl_mode,
                                ssl_root_cert: use_system_ca ? 'system' : ssl_root_cert,
                            }),
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('PostgreSQL integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create PostgreSQL integration')
                    throw error
                }
            },
        },
    })),
])
