import { IconWarning } from '@posthog/icons'
import { LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { EmailOutcome, HogInvocationRow, RunStatus } from './hogInvocationsLogic'

const tagTypeForStatus = (status: RunStatus): LemonTagProps['type'] => {
    switch (status) {
        case 'succeeded':
            return 'success'
        case 'failed':
            return 'danger'
        case 'canceled':
            return 'muted'
        case 'running':
        default:
            return 'warning'
    }
}

const EMAIL_OUTCOME_TAG: Record<EmailOutcome, { label: string; description: string }> = {
    bounced: {
        label: 'Email bounced',
        description:
            "The run finished, but the recipient's mail server refused the email. Expand the row to see the recipient and the reason.",
    },
    complained: {
        label: 'Marked as spam',
        description:
            'The run finished, but the recipient marked the email as spam. Expand the row to see the recipient.',
    },
}

export function RunStatusCell({ row }: { row: HogInvocationRow }): JSX.Element {
    const succeeded = row.status === 'succeeded'
    const showWarningIcon = succeeded && row.problem_log_level !== null
    return (
        <div className="flex flex-wrap items-center gap-1">
            <LemonTag type={tagTypeForStatus(row.status)}>{row.status.toUpperCase()}</LemonTag>
            {succeeded && row.email_outcome ? (
                <Tooltip title={EMAIL_OUTCOME_TAG[row.email_outcome].description}>
                    <LemonTag type="danger">{EMAIL_OUTCOME_TAG[row.email_outcome].label}</LemonTag>
                </Tooltip>
            ) : null}
            {showWarningIcon ? (
                <Tooltip
                    title={
                        row.problem_log_level === 'error'
                            ? 'This run finished but logged an error. Expand the row to view it.'
                            : 'This run finished but logged a warning. Expand the row to view it.'
                    }
                >
                    <IconWarning
                        className={
                            row.problem_log_level === 'error' ? 'text-danger text-base' : 'text-warning text-base'
                        }
                    />
                </Tooltip>
            ) : null}
        </div>
    )
}
