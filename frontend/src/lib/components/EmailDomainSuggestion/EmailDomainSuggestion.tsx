import { Link } from 'lib/lemon-ui/Link'
import { suggestEmailDomain } from 'lib/utils/emailDomainSuggestion'

export function EmailDomainSuggestion({
    email,
    onAccept,
}: {
    email: string
    onAccept: (email: string) => void
}): JSX.Element | null {
    const suggestion = suggestEmailDomain(email)

    if (!suggestion) {
        return null
    }

    return (
        <div className="text-xs text-secondary">
            Did you mean{' '}
            <Link data-attr="email-domain-suggestion" onClick={() => onAccept(suggestion)}>
                {suggestion}
            </Link>
            ?
        </div>
    )
}
