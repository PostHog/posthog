import { formatJsonForHcl } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { CyclotronJobFiltersType, HogFunctionType } from '~/types'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'

export interface HogFunctionHclExportOptions extends HclExportOptions {
    /** Map of alert IDs to their TF references */
    alertIdReplacements?: Map<string, string>
}

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/hog_function
 */
const HOG_FUNCTION_FIELD_MAPPINGS: FieldMapping<Partial<HogFunctionType>, HogFunctionHclExportOptions>[] = [
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
        source: 'execution_order',
        target: 'execution_order',
        shouldInclude: (v) => v !== undefined && v !== null,
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
        transform: (v, _, options) => {
            // bytecode is computed on the server, no need to confuse our users by including that.
            const { bytecode, ...rest } = v as CyclotronJobFiltersType
            let result = `jsonencode(${formatJsonForHcl(rest)})`
            if (options.alertIdReplacements?.size) {
                for (const [alertId, tfRef] of options.alertIdReplacements) {
                    result = result.replace(new RegExp(`"${alertId}"`, 'g'), tfRef)
                }
            }
            return result
        },
    },
    {
        source: 'mappings',
        target: 'mappings_json',
        shouldInclude: (v) => Array.isArray(v) && v.length > 0,
        transform: (v) => `jsonencode(${formatJsonForHcl(v)})`,
    },
    {
        source: 'masking',
        target: 'masking_json',
        shouldInclude: (v) => !!v && typeof v === 'object' && Object.keys(v as object).length > 0,
        transform: (v) => `jsonencode(${formatJsonForHcl(v)})`,
    },
    {
        source: 'template',
        target: 'template_id',
        shouldInclude: (v) => !!(v as HogFunctionType['template'])?.id,
        transform: (v) => `"${(v as HogFunctionType['template'])?.id}"`,
    },
    {
        source: 'icon_url',
        target: 'icon_url',
        shouldInclude: (v) => !!v,
    },
]

function validateHogFunction(
    hogFunction: Partial<HogFunctionType>,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars Needed to align with interface
    _options: HogFunctionHclExportOptions
): string[] {
    const warnings: string[] = []

    if (!hogFunction.name) {
        warnings.push('No name provided. Consider adding a name for better identification in Terraform state.')
    }

    if (hogFunction.inputs) {
        const secretInputs = Object.entries(hogFunction.inputs).filter(([, input]) => input?.secret)
        if (secretInputs.length > 0) {
            warnings.push(
                `Secret inputs (${secretInputs.map(([k]) => k).join(', ')}) in the export, please be careful when handling this file!`
            )
        }
    }

    return warnings
}

const HOG_FUNCTION_EXPORTER: ResourceExporter<Partial<HogFunctionType>, HogFunctionHclExportOptions> = {
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
    return generateHCL(hogFunction, HOG_FUNCTION_EXPORTER, options)
}
