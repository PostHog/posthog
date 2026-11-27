import { useActions, useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import { authLogic } from '../authLogic'
import { signupLogic } from '../signupLogic'

export function EmailTakenNotice(): JSX.Element | null {
    const { signupEmailTaken } = useValues(signupLogic)
    const { chooseAccountPath } = useActions(authLogic)

    if (!signupEmailTaken) {
        return null
    }
    return (
        <p className="-mt-2 mb-0 text-sm text-secondary">
            <Link
                onClick={() => chooseAccountPath('login', true)}
                data-attr="auth-email-taken-login"
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
            >
                Log in instead
            </Link>
            <span>. Signed up with a version of this address with dots or a +tag? Log in with that one.</span>
        </p>
    )
}
