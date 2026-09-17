import api from 'lib/api'
import { getAppContext } from 'lib/utils/getAppContext'
import { userLogic } from 'scenes/userLogic'

import type { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import type { TeamType } from '~/types'

export type ProductIntentMetadata = Record<string, unknown>

// A staff member clicking around as the customer is not the customer's intent. The endpoint
// refuses the write during impersonation, and the loader turns that 403 into a toast, so never
// send it. The loaded user comes first because OAuth mode has no server-rendered app context.
function isImpersonating(): boolean {
    const user = userLogic.findMounted()?.values.user ?? getAppContext()?.current_user
    return !!user?.is_impersonated
}

export type ProductIntentProperties = {
    product_type: ProductKey
    intent_context: ProductIntentContext
    metadata?: ProductIntentMetadata
}

export function addProductIntent(properties: ProductIntentProperties): Promise<TeamType | null> {
    if (isImpersonating()) {
        return Promise.resolve(null)
    }
    return api.productIntents.update(properties)
}

export type ProductCrossSellProperties = {
    from: ProductKey
    to: ProductKey
    intent_context: ProductIntentContext
    metadata?: ProductIntentMetadata
}

export function addProductIntentForCrossSell(properties: ProductCrossSellProperties): Promise<TeamType | null> {
    if (isImpersonating()) {
        return Promise.resolve(null)
    }
    return api.productIntents.update({
        product_type: properties.to,
        intent_context: properties.intent_context,
        metadata: {
            ...properties.metadata,
            from: properties.from,
            to: properties.to,
            type: 'cross_sell',
        },
    })
}
