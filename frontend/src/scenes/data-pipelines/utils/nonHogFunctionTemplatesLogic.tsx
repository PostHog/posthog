import { Link } from '@posthog/lemon-ui'
import { connect, kea, path, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanizeBatchExportName } from 'scenes/data-pipelines/batch-exports/utils'
import { MANUAL_SOURCE_LINK_MAP, sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { DATA_WAREHOUSE_SOURCE_ICON_MAP } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { userLogic } from 'scenes/userLogic'

import { BATCH_EXPORT_SERVICE_NAMES, HogFunctionTemplateType, SourceConfig } from '~/types'

import { BATCH_EXPORT_ICON_MAP } from '../batch-exports/BatchExportIcon'
import type { nonHogFunctionTemplatesLogicType } from './nonHogFunctionTemplatesLogicType'

export const nonHogFunctionTemplatesLogic = kea<nonHogFunctionTemplatesLogicType>([
    path((key) => ['scenes', 'data-pipelines', 'utils', 'nonHogFunctionTemplatesLogic', key]),

    connect(() => ({
        values: [sourceWizardLogic, ['connectors'], featureFlagLogic, ['featureFlags'], userLogic, ['user']],
    })),

    selectors({
        hogFunctionTemplatesDataWarehouseSources: [
            (s) => [s.connectors],
            (connectors): HogFunctionTemplateType[] => {
                const managed = connectors.map(
                    (connector: SourceConfig): HogFunctionTemplateType => ({
                        id: `managed-${connector.name}`,
                        type: 'source',
                        name: connector.name,
                        icon_url: DATA_WAREHOUSE_SOURCE_ICON_MAP[connector.name],
                        status: connector.unreleasedSource ? 'coming_soon' : 'stable',
                        description: (
                            <>
                                Data will be synced to PostHog and regularly refreshed.{' '}
                                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
                            </>
                        ),
                        hog: '',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: true,
                    })
                )

                const selfManaged = Object.entries(MANUAL_SOURCE_LINK_MAP).map(
                    ([type, name]): HogFunctionTemplateType => ({
                        id: `self-managed-${type}`,
                        type: 'source',
                        name,
                        icon_url: DATA_WAREHOUSE_SOURCE_ICON_MAP[type],
                        status: 'stable',
                        description: (
                            <>
                                Data will be queried directly from your data source that you manage.{' '}
                                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
                            </>
                        ),
                        hog: '',
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
                const httpEnabled =
                    featureFlags[FEATURE_FLAGS.BATCH_EXPORTS_POSTHOG_HTTP] || user?.is_impersonated || user?.is_staff
                // HTTP is currently only used for Cloud to Cloud migrations and shouldn't be accessible to users
                const services = BATCH_EXPORT_SERVICE_NAMES.filter((service) =>
                    httpEnabled ? true : service !== ('HTTP' as const)
                )

                return services.map(
                    (service): HogFunctionTemplateType => ({
                        id: `batch-export-${service}`,
                        type: 'destination',
                        name: humanizeBatchExportName(service),
                        icon_url: BATCH_EXPORT_ICON_MAP[service],
                        status: 'stable',
                        hog: '',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: false,
                        description: `${service} batch export`,
                    })
                )
            },
        ],

        // Add another for plugin destinations

        // Add another for batch exports
    }),
])
