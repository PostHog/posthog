import { SourceFieldConfig } from '~/queries/schema/schema-general'

export function shouldHideSourceField(sourceName: string, field: SourceFieldConfig): boolean {
    // BigQuery now uses Google service-account integrations in the UI.
    // Legacy inline key_file auth remains backend-compatible for existing sources.
    return sourceName === 'BigQuery' && field.type === 'file-upload' && field.name === 'key_file'
}
