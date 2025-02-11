import { DESTINATION_PLUGINS, TRANSFORMATION_PLUGINS } from '../legacy-plugins'
import { template as webhookTemplate } from './_destinations/webhook/webhook.template'
import { template as defaultTransformationTemplate } from './_transformations/default/default.template'
import { template as geoipTemplate } from './_transformations/geoip/geoip.template'
import { template as ipAnonymizationTemplate } from './_transformations/ip-anonymization/ip-anonymization.template'
import { template as removeNullPropertiesTemplate } from './_transformations/remove-null-properties/remove-null-properties.template'
import { HogFunctionTemplate } from './types'

export const HOG_FUNCTION_TEMPLATES_DESTINATIONS: HogFunctionTemplate[] = [webhookTemplate]

export const HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS: HogFunctionTemplate[] = [
    defaultTransformationTemplate,
    geoipTemplate,
    ipAnonymizationTemplate,
    removeNullPropertiesTemplate,
]

export const HOG_FUNCTION_TEMPLATES_DESTINATIONS_DEPRECATED: HogFunctionTemplate[] = DESTINATION_PLUGINS.map(
    (plugin) => plugin.template
)

export const HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS_DEPRECATED: HogFunctionTemplate[] = TRANSFORMATION_PLUGINS.map(
    (plugin) => plugin.template
)

export const HOG_FUNCTION_TEMPLATES: HogFunctionTemplate[] = [
    ...HOG_FUNCTION_TEMPLATES_DESTINATIONS,
    ...HOG_FUNCTION_TEMPLATES_DESTINATIONS_DEPRECATED,
    ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS,
    ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS_DEPRECATED,
]
