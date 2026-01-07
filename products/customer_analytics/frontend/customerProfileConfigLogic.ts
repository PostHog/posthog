import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { CustomerProfileConfigType, CustomerProfileScope } from '~/types'

import type { customerProfileConfigLogicType } from './customerProfileConfigLogicType'

export interface CustomerProfileConfigLogicProps {
    scope?: CustomerProfileScope
}

export const customerProfileConfigLogic = kea<customerProfileConfigLogicType>([
    path(['products', 'customer_analytics', 'customerProfileConfigLogic']),
    props({} as CustomerProfileConfigLogicProps),
    key((props) => props.scope || 'all'),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadConfigs: true,
        createConfig: (config: Partial<CustomerProfileConfigType>) => ({ config }),
        updateConfig: (id: CustomerProfileConfigType['id'], config: Partial<CustomerProfileConfigType>) => ({
            id,
            config,
        }),
        deleteConfig: (id: CustomerProfileConfigType['id']) => ({ id }),
        setConfigs: (configs: CustomerProfileConfigType[]) => ({ configs }),
    }),

    loaders(({ props, values }) => ({
        configs: [
            [] as CustomerProfileConfigType[],
            {
                loadConfigs: async () => {
                    try {
                        const params = props.scope ? { scope: props.scope } : {}
                        const response = await api.customerProfileConfigs.list(params)
                        return response.results
                    } catch (error) {
                        lemonToast.error('Failed to load customer profile configs')
                        throw error
                    }
                },
                createConfig: async ({ config }) => {
                    try {
                        const newConfig = await api.customerProfileConfigs.create(config)
                        lemonToast.success('Customer profile config created successfully')
                        return [...values.configs, newConfig]
                    } catch (error) {
                        lemonToast.error('Failed to create customer profile config')
                        throw error
                    }
                },
                updateConfig: async ({ id, config }) => {
                    try {
                        const updatedConfig = await api.customerProfileConfigs.update(id, config)
                        lemonToast.success('Customer profile config updated successfully')
                        return values.configs.map((c) => (c.id === id ? updatedConfig : c))
                    } catch (error) {
                        lemonToast.error('Failed to update customer profile config')
                        throw error
                    }
                },
                deleteConfig: async ({ id }) => {
                    try {
                        await api.customerProfileConfigs.delete(id)
                        lemonToast.success('Customer profile config deleted successfully')
                        return values.configs.filter((c) => c.id !== id)
                    } catch (error) {
                        lemonToast.error('Failed to delete customer profile config')
                        throw error
                    }
                },
            },
        ],
    })),

    selectors({
        personProfileConfig: [
            (s) => [s.configs],
            (configs): CustomerProfileConfigType | undefined => configs.find((c) => c.scope === 'person'),
        ],
    }),

    listeners(({ actions }) => ({
        createConfigSuccess: () => {
            actions.loadConfigs()
        },
        updateConfigSuccess: () => {
            actions.loadConfigs()
        },
        deleteConfigSuccess: () => {
            actions.loadConfigs()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadConfigs()
    }),
])
