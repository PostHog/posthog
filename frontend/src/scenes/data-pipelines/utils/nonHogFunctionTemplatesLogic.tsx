import { connect, kea, path, props, selectors } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS, FeatureFlagLookupKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanizeBatchExportName } from 'scenes/data-pipelines/batch-exports/utils'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { DATA_WAREHOUSE_SOURCE_ICON_MAP } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { userLogic } from 'scenes/userLogic'

import { SourceConfig } from '~/queries/schema/schema-general'
import { BATCH_EXPORT_SERVICE_NAMES, HogFunctionTemplateType } from '~/types'

import { BATCH_EXPORT_ICON_MAP } from '../batch-exports/BatchExportIcon'
import type { nonHogFunctionTemplatesLogicType } from './nonHogFunctionTemplatesLogicType'

export interface NonHogFunctionTemplatesLogicProps {
    availableSources: Record<string, SourceConfig>
}

export const nonHogFunctionTemplatesLogic = kea<nonHogFunctionTemplatesLogicType>([
    props({} as NonHogFunctionTemplatesLogicProps),
    path((key) => ['scenes', 'data-pipelines', 'utils', 'nonHogFunctionTemplatesLogic', key]),

    connect(({ availableSources }: NonHogFunctionTemplatesLogicProps) => ({
        values: [
            sourceWizardLogic({ availableSources }),
            ['connectors', 'manualConnectors'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
        ],
    })),

    selectors({
        hogFunctionTemplatesDataWarehouseSources: [
            (s) => [s.connectors, s.manualConnectors, s.featureFlags],
            (connectors, manualConnectors, featureFlags): HogFunctionTemplateType[] => {
                const managed = connectors.map((connector: SourceConfig): HogFunctionTemplateType => {
                    const featureFlagKey = Object.keys(FEATURE_FLAGS).find(
                        (k) => FEATURE_FLAGS[k as FeatureFlagLookupKey] === connector.featureFlag
                    )
                    const featureFlagEnabledForUser =
                        featureFlagKey && featureFlags[FEATURE_FLAGS[featureFlagKey as FeatureFlagLookupKey]]
                    // explicitly checks for no provided or no matching feature flag
                    const isUnreleasedAndShouldntAccess =
                        (connector.unreleasedSource && !featureFlagKey) ||
                        (connector.unreleasedSource && !featureFlagEnabledForUser)
                    return {
                        id: `managed-${connector.name}`,
                        type: 'source',
                        name: connector.label ?? connector.name,
                        icon_url: connector.iconPath,
                        status: isUnreleasedAndShouldntAccess
                            ? 'coming_soon'
                            : connector.betaSource
                              ? 'beta'
                              : 'stable',
                        description: isUnreleasedAndShouldntAccess ? (
                            'Get notified when this source is available to connect'
                        ) : (
                            <>
                                Data will be synced to PostHog and regularly refreshed.{' '}
                                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
                            </>
                        ),
                        code: '',
                        code_language: 'hog',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: true,
                        flag: connector.featureFlag,
                    }
                })
                const selfManaged = manualConnectors.map(
                    (source): HogFunctionTemplateType => ({
                        id: `self-managed-${source.type}`,
                        type: 'source',
                        name: source.name,
                        icon_url: DATA_WAREHOUSE_SOURCE_ICON_MAP[source.type],
                        status: 'stable',
                        description: (
                            <>
                                Data will be queried directly from your data source that you manage.{' '}
                                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
                            </>
                        ),
                        code: '',
                        code_language: 'hog',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: true,
                    })
                )

                return [...managed, ...selfManaged]
            },
        ],

        hogFunctionTemplatesBatchExports: [
            (s) => [s.featureFlags, s.user],
            (featureFlags, user): HogFunctionTemplateType[] => {
                // HTTP is currently only used for Cloud to Cloud migrations and shouldn't be accessible to users
                const httpEnabled =
                    featureFlags[FEATURE_FLAGS.BATCH_EXPORTS_POSTHOG_HTTP] || user?.is_impersonated || user?.is_staff
                // Databricks is currently behind a feature flag
                const databricksEnabled = featureFlags[FEATURE_FLAGS.BATCH_EXPORTS_DATABRICKS]

                const services = BATCH_EXPORT_SERVICE_NAMES.filter(
                    (service) =>
                        (httpEnabled ? true : service !== ('HTTP' as const)) &&
                        (databricksEnabled ? true : service !== ('Databricks' as const))
                )

                return services.map(
                    (service): HogFunctionTemplateType => ({
                        id: `batch-export-${service}`,
                        type: 'destination',
                        name: humanizeBatchExportName(service),
                        icon_url: BATCH_EXPORT_ICON_MAP[service],
                        status: service === 'Databricks' ? 'beta' : 'stable',
                        code: '',
                        code_language: 'hog',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: false,
                        description: `${service} batch export`,
                    })
                )
            },
        ],
    }),
])
