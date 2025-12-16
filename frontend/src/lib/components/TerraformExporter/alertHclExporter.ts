import { formatHclValue, sanitizeResourceName } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { AlertType } from '~/lib/components/Alerts/types'
import { HogFunctionType } from '~/types'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'
import { generateHogFunctionHCL } from './hogFunctionHclExporter'

export interface AlertHclExportOptions extends HclExportOptions {
    /** When provided, uses TF reference instead of hardcoded insight_id */
    insightTfReference?: string
    /** Child hog functions to include in export */
    hogFunctions?: HogFunctionType[]
}

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/alert
 */
const ALERT_FIELD_MAPPINGS: FieldMapping<Partial<AlertType>>[] = [
    {
        source: 'name',
        target: 'name',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'enabled',
        target: 'enabled',
        shouldInclude: () => true,
    },
    {
        source: 'calculation_interval',
        target: 'calculation_interval',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'condition',
        target: 'condition_type',
        shouldInclude: (v) => !!(v as AlertType['condition'])?.type,
        transform: (v) => formatHclValue((v as AlertType['condition'])?.type),
    },
    {
        source: 'threshold',
        target: 'threshold_type',
        shouldInclude: (v) => !!(v as AlertType['threshold'])?.configuration?.type,
        transform: (v) => formatHclValue((v as AlertType['threshold'])?.configuration?.type),
    },
    {
        source: 'threshold',
        target: 'threshold_lower',
        shouldInclude: (v) => (v as AlertType['threshold'])?.configuration?.bounds?.lower !== undefined,
        transform: (v) => formatHclValue((v as AlertType['threshold'])?.configuration?.bounds?.lower),
    },
    {
        source: 'threshold',
        target: 'threshold_upper',
        shouldInclude: (v) => (v as AlertType['threshold'])?.configuration?.bounds?.upper !== undefined,
        transform: (v) => formatHclValue((v as AlertType['threshold'])?.configuration?.bounds?.upper),
    },
    {
        source: 'config',
        target: 'series_index',
        shouldInclude: (v) => (v as AlertType['config'])?.series_index !== undefined,
        transform: (v) => formatHclValue((v as AlertType['config'])?.series_index),
    },
    {
        source: 'config',
        target: 'check_ongoing_interval',
        shouldInclude: (v) => (v as AlertType['config'])?.check_ongoing_interval !== undefined,
        transform: (v) => formatHclValue((v as AlertType['config'])?.check_ongoing_interval),
    },
    {
        source: 'skip_weekend',
        target: 'skip_weekend',
        shouldInclude: (v) => v === true,
    },
    {
        source: 'insight',
        target: 'insight_id',
        shouldInclude: (v) => (v as AlertType['insight'])?.id !== undefined,
        transform: (v) => formatHclValue((v as AlertType['insight'])?.id),
    },
    {
        source: 'subscribed_users',
        target: 'subscribed_users',
        shouldInclude: (v) => Array.isArray(v),
        transform: (v) => {
            const users = v as Array<{ id: number }>
            return formatHclValue(users.map((u) => u.id))
        },
    },
]

function validateAlert(alert: Partial<AlertType>, options?: AlertHclExportOptions): string[] {
    const warnings: string[] = []

    if (!alert.name) {
        warnings.push('No name provided. Consider adding a name for better identification in Terraform state.')
    }

    if (!alert.threshold?.configuration?.type) {
        warnings.push('Missing required field: threshold_type. The alert will fail to apply without this value.')
    }

    // Only warn about hardcoded insight_id if not using TF reference
    if (!options?.insightTfReference && alert.insight?.id) {
        warnings.push(
            '`insight_id` is hardcoded. Consider referencing the Terraform resource instead (e.g., `posthog_insight.my_insight.id`).'
        )
    }

    if (alert.subscribed_users && alert.subscribed_users.length > 0) {
        warnings.push(
            `\`subscribed_users\` contains internal user IDs. These IDs are specific to this PostHog instance and will need to be updated if deploying to a different environment.`
        )
    }

    return warnings
}

const ALERT_EXPORTER: ResourceExporter<Partial<AlertType>> = {
    resourceType: 'posthog_alert',
    resourceLabel: 'alert',
    fieldMappings: ALERT_FIELD_MAPPINGS,
    validate: (alert) => validateAlert(alert),
    getResourceName: (a) => a.name || `alert_${a.id || 'new'}`,
    getId: (a) => a.id,
}

export function generateAlertHCL(alert: Partial<AlertType>, options: AlertHclExportOptions = {}): HclExportResult {
    const allWarnings: string[] = []
    const hclSections: string[] = []

    // Generate base HCL
    const result = generateHCL(
        alert,
        {
            ...ALERT_EXPORTER,
            validate: (a) => validateAlert(a, options),
        },
        options
    )

    let alertHcl = result.hcl
    allWarnings.push(...result.warnings)

    // Replace hardcoded insight_id with TF reference when provided
    if (options.insightTfReference && alert.insight?.id !== undefined) {
        alertHcl = alertHcl.replace(
            `insight_id = ${formatHclValue(alert.insight.id)}`,
            `insight_id = ${options.insightTfReference}`
        )
    }

    hclSections.push(alertHcl)

    // Generate child hog functions if provided
    if (options.hogFunctions && options.hogFunctions.length > 0) {
        const alertTfName = sanitizeResourceName(ALERT_EXPORTER.getResourceName(alert), ALERT_EXPORTER.resourceLabel)
        const alertTfReference = `${ALERT_EXPORTER.resourceType}.${alertTfName}.id`

        for (const hogFunction of options.hogFunctions) {
            const hogFunctionResult = generateHogFunctionHCL(hogFunction, {
                alertTfReference,
                alertId: alert.id,
            })
            hclSections.push('')
            hclSections.push(hogFunctionResult.hcl)
            allWarnings.push(
                ...hogFunctionResult.warnings.map((w) => `[Hog Function: ${hogFunction.name || hogFunction.id}] ${w}`)
            )
        }
    }

    return {
        hcl: hclSections.join('\n'),
        warnings: allWarnings,
    }
}
