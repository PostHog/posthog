import { useActions, useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import { authLogic } from '../authLogic'

const LINK_CLASS_NAME =
    'font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning'

export function LoginSignupLink(): JSX.Element | null {
    const { canSignUpWithEmail, accountExists } = useValues(authLogic)
    const { chooseAccountPath } = useActions(authLogic)

    if (!canSignUpWithEmail) {
        return null
    }
    // The precheck failed, so this may be a new person. Signup still refuses an email that has an account.
    if (accountExists === null) {
        return (
            <p className="mt-4 mb-0 text-sm text-secondary text-center">
                <span>New to PostHog?</span>{' '}
                <Link
                    onClick={() => chooseAccountPath('signup', null)}
                    data-attr="auth-unknown-account-signup"
                    className={LINK_CLASS_NAME}
                >
                    Create an account
                </Link>
            </p>
        )
    }
    if (accountExists === false) {
        return (
            <p className="mt-4 mb-0 text-sm text-secondary text-center">
                <Link
                    onClick={() => chooseAccountPath('signup', false)}
                    data-attr="auth-sso-domain-signup-with-email"
                    className={LINK_CLASS_NAME}
                >
                    Sign up with email instead
                </Link>
            </p>
        )
    }
    return null
}
