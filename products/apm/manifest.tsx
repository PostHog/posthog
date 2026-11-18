/**
 * Product manifest for APM.
 *
 * The first surface is the Application observability services list, behind the product flag.
 * The anomaly detector in the backend stays a dependency of the logs, tracing, and metrics
 * products and has no surface of its own here yet.
 */
import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'APM',
    scenes: {
        ApplicationObservability: {
            name: 'Application observability',
            import: () => import('./frontend/ApplicationObservabilityScene'),
            projectBased: true,
            layout: 'app-container',
            activityScope: 'Tracing',
            description: 'Whether your application is OK, one row per service, from the signals you already send.',
            iconType: 'tracing',
        },
        ApplicationObservabilityService: {
            name: 'Service',
            import: () => import('./frontend/servicePage/ServicePageScene'),
            projectBased: true,
            layout: 'app-container',
            activityScope: 'Tracing',
            description: 'Requests, errors, latency and endpoints for one service.',
            iconType: 'tracing',
        },
    },
    routes: {
        '/application-observability': ['ApplicationObservability', 'applicationObservability'],
        '/application-observability/service': ['ApplicationObservabilityService', 'applicationObservabilityService'],
    },
    redirects: {},
    urls: {
        applicationObservability: (): string => '/application-observability',
        // The service is a query param because service names are free text. The router reads `1.0`
        // back as the number 1 and `true` as a boolean, so values that look like either go in as a
        // one-item list, which it keeps as written. Mirrors `scopeParamValue` in servicePage.ts.
        applicationObservabilityService: (
            serviceName: string,
            params?: {
                range?: string | null
                environment?: string | null
                version?: string | null
                operation?: string | null
            }
        ): string => {
            const asText = (value: string): string | string[] =>
                /^(true|false)$/i.test(value) || (value.trim() !== '' && !Number.isNaN(Number(value))) ? [value] : value
            const query: Record<string, string | string[]> = { service: asText(serviceName) }
            if (params?.range && params.range !== '-1h') {
                query.range = params.range
            }
            for (const key of ['environment', 'version', 'operation'] as const) {
                const value = params ? params[key] : null
                if (value || (key === 'environment' && value === '')) {
                    query[key] = asText(value)
                }
            }
            return combineUrl('/application-observability/service', query).url
        },
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Application observability',
            intents: [ProductKey.TRACING],
            category: ProductItemCategory.MONITORING,
            iconType: 'tracing' as FileSystemIconType,
            iconColor: [
                'var(--color-product-tracing-light)',
                'var(--color-product-tracing-dark)',
            ] as FileSystemIconColor,
            href: '/application-observability',
            flag: FEATURE_FLAGS.APPLICATION_OBSERVABILITY,
            sceneKey: 'ApplicationObservability',
        },
    ],
}
