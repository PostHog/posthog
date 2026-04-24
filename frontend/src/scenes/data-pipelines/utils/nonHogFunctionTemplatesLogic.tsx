import { connect, kea, path, props, selectors } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS, type FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanizeBatchExportName } from 'scenes/data-pipelines/batch-exports/utils'
import { userLogic } from 'scenes/userLogic'

import { SourceConfig } from '~/queries/schema/schema-general'
import { BATCH_EXPORT_SERVICE_NAMES, HogFunctionTemplateStatus, HogFunctionTemplateType } from '~/types'

import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import { DATA_WAREHOUSE_SOURCE_ICON_MAP } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { BATCH_EXPORT_ICON_MAP } from '../batch-exports/BatchExportIcon'
import type { nonHogFunctionTemplatesLogicType } from './nonHogFunctionTemplatesLogicType'

export interface NonHogFunctionTemplatesLogicProps {
    availableSources: Record<string, SourceConfig>
}

type SourceDisplayStatus = {
    status: HogFunctionTemplateStatus
    descriptionEl: string | JSX.Element
}

function getSourceDisplayStatus(unreleased: boolean, featureFlag: boolean | undefined): SourceDisplayStatus {
    const unreleasedDescriptionEl = 'Get notified when this source is available to connect'
    const releasedDescriptionEl = (
        <>
            Data will be synced to PostHog and regularly refreshed.{' '}
            <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
        </>
    )
    // regardless of release status, those passing the feature flag should see a released source
    if (featureFlag === true) {
        return {
            status: 'stable',
            descriptionEl: releasedDescriptionEl,
        }
    }
    // regardless of release status, those failing the feature flag should see an unreleased source
    if (featureFlag === false) {
        return {
            status: 'coming_soon',
            descriptionEl: unreleasedDescriptionEl,
        }
    }
    // if the feature flag is undefined, fall back to the source's unreleased state
    return {
        status: unreleased ? 'coming_soon' : 'stable',
        descriptionEl: unreleased ? unreleasedDescriptionEl : releasedDescriptionEl,
    }
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
                // A source gated behind a feature flag should be hidden entirely when the flag
                // isn't enabled for the user — regardless of its releaseStatus.
                const visibleConnectors = connectors.filter((connector: SourceConfig) => {
                    if (connector.featureFlag === undefined) {
                        return true
                    }
                    return !!featureFlags[connector.featureFlag as FeatureFlagKey]
                })
                const managed = visibleConnectors.map((connector: SourceConfig): HogFunctionTemplateType => {
                    const featureFlagDefined = connector.featureFlag !== undefined
                    const featureFlagRaw = featureFlags[connector.featureFlag as FeatureFlagKey]
                    let featureFlagValue: boolean | undefined = undefined
                    if (featureFlagDefined && featureFlagRaw !== undefined) {
                        featureFlagValue = !!featureFlagRaw
                    }
                    const unreleasedValue = !!connector.unreleasedSource
                    const { status, descriptionEl } = getSourceDisplayStatus(unreleasedValue, featureFlagValue)
                    // Only surface alpha/beta while the source is actually connectable — a source
                    // that renders as "coming_soon" (Roadmap tag) shouldn't also advertise "Beta".
                    const releaseStatus =
                        status === 'stable' && connector.releaseStatus && connector.releaseStatus !== 'ga'
                            ? connector.releaseStatus
                            : undefined

                    return {
                        id: `managed-${connector.name}`,
                        type: 'source',
                        name: connector.label ?? connector.name,
                        icon_url: connector.iconPath,
                        icon_class_name: connector.iconClassName,
                        status: status,
                        description: descriptionEl,
                        code: '',
                        code_language: 'hog',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: true,
                        featured: connector.featured ?? false,
                        releaseStatus,
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

                const services = BATCH_EXPORT_SERVICE_NAMES.filter((service) =>
                    httpEnabled ? true : service !== ('HTTP' as const)
                )

                return services.map(
                    (service): HogFunctionTemplateType => ({
                        id: `batch-export-${service}`,
                        type: 'destination',
                        name: humanizeBatchExportName(service),
                        icon_url: BATCH_EXPORT_ICON_MAP[service],
                        status: service === 'Databricks' ? 'beta' : service === 'AzureBlob' ? 'beta' : 'stable',
                        code: '',
                        code_language: 'hog',
                        inputs_schema: [],
                        filters: null,
                        masking: null,
                        free: false,
                        description: `${humanizeBatchExportName(service)} batch export`,
                    })
                )
            },
        ],
    }),
])
