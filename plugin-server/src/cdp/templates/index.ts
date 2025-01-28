import { template as webhookTemplate } from './_destinations/webhook/webhook.template'
import { template as defaultTemplate } from './_transformations/default/default.template'
import { template as geoipTemplate } from './_transformations/geoip/geoip.template'

export const DESTINATION_TEMPLATES = [webhookTemplate]
export const TRANSFORMATION_TEMPLATES = [geoipTemplate, defaultTemplate]

export const ALL_TEMPLATES = [...DESTINATION_TEMPLATES, ...TRANSFORMATION_TEMPLATES]
