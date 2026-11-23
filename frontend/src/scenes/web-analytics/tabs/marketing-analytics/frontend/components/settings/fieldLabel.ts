import { MarketingAnalyticsColumnsSchemaNames } from '~/queries/schema/schema-general'

export function fieldLabel(fieldName: MarketingAnalyticsColumnsSchemaNames): string {
    return fieldName.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
}
