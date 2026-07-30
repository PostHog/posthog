import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { DatabaseSchemaTableCertification } from '~/queries/schema/schema-general'

const STATUS_COPY: Record<DatabaseSchemaTableCertification['status'], { label: string; guidance: string }> = {
    certified: { label: 'Certified', guidance: 'Prefer this source.' },
    deprecated: { label: 'Deprecated', guidance: 'Avoid this source.' },
}

function certificationTooltip(certification: DatabaseSchemaTableCertification): JSX.Element {
    const { label, guidance } = STATUS_COPY[certification.status]
    return (
        <div className="flex flex-col gap-1">
            <span>
                {label}. {guidance}
            </span>
            {certification.notes ? <span>{certification.notes}</span> : null}
            {certification.certified_by ? (
                <span className="text-secondary">
                    {label} by {certification.certified_by}
                    {certification.certified_at ? ` (${humanFriendlyDetailedTime(certification.certified_at)})` : ''}
                </span>
            ) : null}
        </div>
    )
}

export function TableCertificationIcon({
    certification,
}: {
    certification?: DatabaseSchemaTableCertification | null
}): JSX.Element | null {
    if (!certification) {
        return null
    }
    return (
        <Tooltip title={certificationTooltip(certification)}>
            {certification.status === 'certified' ? (
                <IconCheckCircle className="shrink-0 text-success" />
            ) : (
                <IconWarning className="shrink-0 text-warning" />
            )}
        </Tooltip>
    )
}

export function TableCertificationTag({
    certification,
}: {
    certification?: DatabaseSchemaTableCertification | null
}): JSX.Element | null {
    if (!certification) {
        return null
    }
    return (
        <Tooltip title={certificationTooltip(certification)}>
            <LemonTag type={certification.status === 'certified' ? 'success' : 'warning'}>
                {STATUS_COPY[certification.status].label}
            </LemonTag>
        </Tooltip>
    )
}
