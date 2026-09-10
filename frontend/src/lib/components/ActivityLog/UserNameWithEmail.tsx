import { Tooltip } from 'lib/lemon-ui/Tooltip'

/**
 * A person's name in an activity log line, with their email on hover. Organizations often have
 * several members who share a first name, and many accounts carry no last name, so the name alone
 * can be ambiguous. Callers pass no email when the row must not disclose one.
 */
export function UserNameWithEmail({ name, email }: { name: string; email?: string | null }): JSX.Element {
    if (!email || email === name) {
        return <strong className="ph-no-capture">{name}</strong>
    }
    return (
        <Tooltip title={<span className="ph-no-capture">{email}</span>}>
            <strong className="ph-no-capture cursor-help">{name}</strong>
        </Tooltip>
    )
}
