import { Link } from 'lib/lemon-ui/Link'

export function CreateAccountTerms(): JSX.Element {
    return (
        <p className="AuthScene__terms mt-5 mb-0 text-xs leading-relaxed text-tertiary text-center">
            <span>By creating an account, you agree to our</span>{' '}
            <Link to="https://posthog.com/terms" target="_blank">
                Terms of Service ↗
            </Link>{' '}
            <span>and</span>{' '}
            <Link to="https://posthog.com/privacy" target="_blank">
                Privacy Policy ↗
            </Link>
            <span>.</span>
        </p>
    )
}
