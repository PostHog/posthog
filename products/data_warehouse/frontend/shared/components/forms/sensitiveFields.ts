import { SourceFieldConfig } from '~/queries/schema/schema-general'

// A password input or a field marked secret holds a credential. The backend redacts these from
// API responses, so they reload empty when a user edits an existing source.
export const isSensitiveCredentialField = (field: SourceFieldConfig): boolean => {
    return ('secret' in field && !!field.secret) || field.type === 'password'
}
