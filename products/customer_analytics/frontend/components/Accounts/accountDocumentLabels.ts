import type { LemonTagType } from '@posthog/lemon-ui'

import type {
    AccountDocumentApi,
    AccountLegalDocumentApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

export type AccountDocumentType = AccountDocumentApi['document_type']
export type AccountDocumentStatus = AccountDocumentApi['status']
export type AccountDocumentSource = AccountDocumentApi['source']

export const DOCUMENT_TYPE_OPTIONS: { value: AccountDocumentType; label: string }[] = [
    { value: 'quote', label: 'Quote' },
    { value: 'order_form', label: 'Order form' },
    { value: 'msa', label: 'Master service agreement' },
    { value: 'dpa', label: 'Data processing agreement' },
    { value: 'baa', label: 'Business associate agreement' },
    { value: 'nda', label: 'Non-disclosure agreement' },
    { value: 'security_questionnaire', label: 'Security questionnaire' },
    { value: 'other', label: 'Other' },
]

export const DOCUMENT_STATUS_OPTIONS: { value: AccountDocumentStatus; label: string }[] = [
    { value: 'draft', label: 'Draft' },
    { value: 'sent', label: 'Sent' },
    { value: 'signed', label: 'Signed' },
    { value: 'expired', label: 'Expired' },
    { value: 'voided', label: 'Voided' },
]

export const DOCUMENT_SOURCE_OPTIONS: { value: AccountDocumentSource; label: string }[] = [
    { value: 'pandadoc', label: 'PandaDoc document' },
    { value: 'link', label: 'Link' },
]

const STATUS_TAG_TYPES: Record<AccountDocumentStatus, LemonTagType> = {
    draft: 'default',
    sent: 'primary',
    signed: 'success',
    expired: 'warning',
    voided: 'danger',
}

const LEGAL_DOCUMENT_TYPE_LABELS: Record<AccountLegalDocumentApi['document_type'], string> = {
    DPA: 'Data processing agreement',
    BAA: 'Business associate agreement',
    MSA: 'Master service agreement',
}

export function documentTypeLabel(documentType: AccountDocumentType): string {
    return DOCUMENT_TYPE_OPTIONS.find((option) => option.value === documentType)?.label ?? documentType
}

export function documentStatusLabel(status: AccountDocumentStatus): string {
    return DOCUMENT_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
}

export function documentStatusTagType(status: AccountDocumentStatus): LemonTagType {
    return STATUS_TAG_TYPES[status] ?? 'default'
}

export function legalDocumentTypeLabel(documentType: AccountLegalDocumentApi['document_type']): string {
    return LEGAL_DOCUMENT_TYPE_LABELS[documentType] ?? documentType
}

export function legalDocumentStatusLabel(status: AccountLegalDocumentApi['status']): string {
    return status === 'signed' ? 'Signed' : 'Awaiting signature'
}

export function legalDocumentStatusTagType(status: AccountLegalDocumentApi['status']): LemonTagType {
    return status === 'signed' ? 'success' : 'primary'
}
