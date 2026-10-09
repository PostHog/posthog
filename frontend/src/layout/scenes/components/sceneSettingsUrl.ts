import type { SettingSectionId } from 'scenes/settings/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

const SETTINGS_SECTION_BY_PRODUCT: Partial<Record<ProductKey, SettingSectionId>> = {
    [ProductKey.PRODUCT_ANALYTICS]: 'environment-product-analytics',
    [ProductKey.WEB_ANALYTICS]: 'environment-web-analytics',
    [ProductKey.SESSION_REPLAY]: 'environment-replay',
    [ProductKey.FEATURE_FLAGS]: 'environment-feature-flags',
    [ProductKey.EXPERIMENTS]: 'environment-experiments',
    [ProductKey.SURVEYS]: 'environment-surveys',
    [ProductKey.AI_OBSERVABILITY]: 'environment-ai-observability',
    [ProductKey.LOGS]: 'environment-logs',
    [ProductKey.WORKFLOWS]: 'environment-workflows',
}

export function getSceneSettingsUrl(productKey: ProductKey | null): string | null {
    const section = productKey ? SETTINGS_SECTION_BY_PRODUCT[productKey] : undefined
    return section ? urls.settings(section) : null
}
