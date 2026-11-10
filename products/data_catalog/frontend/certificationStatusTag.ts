import type { DataCatalogCertificationApi } from './generated/api.schemas'

export interface CertificationStatusTag {
    label: string
    type: 'warning' | 'success' | 'muted'
}

const STATUS_TAG: Record<string, CertificationStatusTag> = {
    proposed: { label: 'Proposed', type: 'warning' },
    certified: { label: 'Certified', type: 'success' },
    deprecated: { label: 'Deprecated', type: 'muted' },
}

export function certificationStatusTag(
    certification: Pick<DataCatalogCertificationApi, 'status' | 'proposed_status'>
): CertificationStatusTag {
    if (certification.status === 'proposed' && certification.proposed_status === 'deprecated') {
        return { label: 'Deprecation proposed', type: 'warning' }
    }
    return STATUS_TAG[certification.status] ?? { label: certification.status, type: 'muted' }
}
