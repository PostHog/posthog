import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { shopifySetupModalLogicType } from './shopifySetupModalLogicType'

export interface ShopifySetupModalLogicProps {
    isOpen: boolean
    onComplete: (integrationId?: number) => void
}

export const shopifySetupModalLogic = kea<shopifySetupModalLogicType>([
    path(['integrations', 'shopify', 'shopifySetupModalLogic']),
    props({} as ShopifySetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        shopifyIntegration: {
            defaults: {
                shop: '',
            },
            errors: ({ shop }) => ({
                shop: shop.trim() ? undefined : 'Store name is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'shopify',
                        config: {
                            shop: values.shopifyIntegration.shop.trim(),
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Shopify integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create Shopify integration')
                    throw error
                }
            },
        },
    })),
])
