import { formatJsonForHcl } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { HogFunctionType } from '~/types'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'

export interface HogFunctionHclExportOptions extends HclExportOptions {
    /** When provided, replaces hardcoded alert_id in filters with TF reference */
    alertTfReference?: string
    /** The alert ID to replace the TF reference */
    alertId?: string
}

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/hog_function
 */
const HOG_FUNCTION_FIELD_MAPPINGS: FieldMapping<Partial<HogFunctionType>>[] = [
    {
        source: 'name',
        target: 'name',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'description',
        target: 'description',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'type',
        target: 'type',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'enabled',
        target: 'enabled',
        shouldInclude: () => true,
    },
    {
        source: 'hog',
        target: 'hog',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'inputs_schema',
        target: 'inputs_schema_json',
        shouldInclude: (v) => Array.isArray(v) && v.length > 0,
        transform: (v) => `jsonencode(${formatJsonForHcl(v)})`,
    },
    {
        source: 'inputs',
        target: 'inputs_json',
        shouldInclude: (v) => !!v && typeof v === 'object' && Object.keys(v as object).length > 0,
        transform: (v) => `jsonencode(${formatJsonForHcl(v)})`,
    },
    {
        source: 'filters',
        target: 'filters_json',
        shouldInclude: (v) => !!v && typeof v === 'object' && Object.keys(v as object).length > 0,
        transform: (v) => `jsonencode(${formatJsonForHcl(v)})`,
    },
    {
        source: 'icon_url',
        target: 'icon_url',
        shouldInclude: (v) => !!v,
    },
]

function validateHogFunction(hogFunction: Partial<HogFunctionType>): string[] {
    const warnings: string[] = []

    if (!hogFunction.name) {
        warnings.push('No name provided. Consider adding a name for better identification in Terraform state.')
    }

    // Check if there are secrets in inputs that can't be exported
    if (hogFunction.inputs) {
        const secretInputs = Object.entries(hogFunction.inputs).filter(([, input]) => input?.secret)
        if (secretInputs.length > 0) {
            warnings.push(
                `Secret inputs (${secretInputs.map(([k]) => k).join(', ')}) cannot be exported. You will need to configure these manually after import.`
            )
        }
    }

    return warnings
}

const HOG_FUNCTION_EXPORTER: ResourceExporter<Partial<HogFunctionType>> = {
    resourceType: 'posthog_hog_function',
    resourceLabel: 'hog_function',
    fieldMappings: HOG_FUNCTION_FIELD_MAPPINGS,
    validate: validateHogFunction,
    getResourceName: (h) => h.name || `hog_function_${h.id || 'new'}`,
    getId: (h) => h.id,
}

export function generateHogFunctionHCL(
    hogFunction: Partial<HogFunctionType>,
    options: HogFunctionHclExportOptions = {}
): HclExportResult {
    const result = generateHCL(hogFunction, HOG_FUNCTION_EXPORTER, options)

    // If we have an alert reference, post-process the HCL to replace the hardcoded alert_id
    if (options.alertTfReference && options.alertId) {
        result.hcl = result.hcl.replace(new RegExp(`"${options.alertId}"`, 'g'), options.alertTfReference)
    }

    return result
}
