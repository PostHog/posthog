import { formatHclValue, sanitizeResourceName } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { AlertType } from '~/lib/components/Alerts/types'
import { HogFunctionType } from '~/types'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'
import { generateHogFunctionHCL } from './hogFunctionHclExporter'

export interface AlertHclExportOptions extends HclExportOptions {
    /** When provided, uses TF reference instead of hardcoded insight id */
    insightTfReference?: string
    /** Child hog functions to include in export */
    hogFunctions?: HogFunctionType[]
}

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/alert
 */
const ALERT_FIELD_MAPPINGS: FieldMapping<Partial<AlertType>, AlertHclExportOptions>[] = [
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
        shouldInclude: (_, alert) => !!alert.condition?.type,
        transform: (_, alert) => formatHclValue(alert.condition?.type),
    },
    {
        source: 'threshold',
        target: 'threshold_type',
        shouldInclude: (_, alert) => !!alert.threshold?.configuration?.type,
        transform: (_, alert) => formatHclValue(alert.threshold?.configuration?.type),
    },
    {
        source: 'threshold',
        target: 'threshold_lower',
        shouldInclude: (_, alert) => alert.threshold?.configuration?.bounds?.lower !== undefined,
        transform: (_, alert) => formatHclValue(alert.threshold?.configuration?.bounds?.lower),
    },
    {
        source: 'threshold',
        target: 'threshold_upper',
        shouldInclude: (_, alert) => alert.threshold?.configuration?.bounds?.upper !== undefined,
        transform: (_, alert) => formatHclValue(alert.threshold?.configuration?.bounds?.upper),
    },
    {
        source: 'config',
        target: 'series_index',
        shouldInclude: (_, alert) => alert.config?.series_index !== undefined,
        transform: (_, alert) => formatHclValue(alert.config?.series_index),
    },
    {
        source: 'config',
        target: 'check_ongoing_interval',
        shouldInclude: (_, alert) => alert.config?.check_ongoing_interval !== undefined,
        transform: (_, alert) => formatHclValue(alert.config?.check_ongoing_interval),
    },
    {
        source: 'skip_weekend',
        target: 'skip_weekend',
        shouldInclude: (v) => v === true,
    },
    {
        source: 'insight',
        target: 'insight',
        shouldInclude: (_, alert) => alert.insight?.id !== undefined,
        transform: (_, alert, options) => {
            const insightId = alert.insight?.id
            if (options.insightTfReference && insightId !== undefined) {
                return options.insightTfReference
            }
            return formatHclValue(insightId)
        },
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

    // Only warn about hardcoded insight id if not using TF reference
    if (!options?.insightTfReference && alert.insight?.id) {
        warnings.push(
            '`insight id` is hardcoded. Consider referencing the Terraform resource instead (e.g., `posthog_insight.my_insight.id`).'
        )
    }

    if (alert.subscribed_users && alert.subscribed_users.length > 0) {
        warnings.push(
            '`subscribed_users` contains internal user IDs. These IDs are specific to this PostHog instance and will need to be updated if deploying to a different environment.'
        )
    }

    return warnings
}

const ALERT_EXPORTER: ResourceExporter<Partial<AlertType>, AlertHclExportOptions> = {
    resourceType: 'posthog_alert',
    resourceLabel: 'alert',
    fieldMappings: ALERT_FIELD_MAPPINGS,
    validate: validateAlert,
    getResourceName: (a) => a.name || `alert_${a.id || 'new'}`,
    getId: (a) => a.id,
}

export function generateAlertHCL(alert: Partial<AlertType>, options: AlertHclExportOptions = {}): HclExportResult {
    const allWarnings: string[] = []
    const hclSections: string[] = []

    const result = generateHCL(alert, ALERT_EXPORTER, options)
    allWarnings.push(...result.warnings)
    hclSections.push(result.hcl)

    // Generate child hog functions if provided
    if (options.hogFunctions && options.hogFunctions.length > 0) {
        const alertIdReplacements = new Map<string, string>()
        if (alert.id) {
            const alertTfName = sanitizeResourceName(
                ALERT_EXPORTER.getResourceName(alert),
                ALERT_EXPORTER.resourceLabel
            )
            const alertTfReference = `${ALERT_EXPORTER.resourceType}.${alertTfName}.id`
            alertIdReplacements.set(alert.id, alertTfReference)
        }

        for (const hogFunction of options.hogFunctions) {
            const hogFunctionResult = generateHogFunctionHCL(hogFunction, { alertIdReplacements })
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
