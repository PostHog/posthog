import { useActions } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import { authLogic } from '../authLogic'

export function UseDifferentEmailLink(): JSX.Element {
    const { backToEmail } = useActions(authLogic)

    return (
        <p className="mt-5 mb-0 text-sm text-secondary text-center">
            <Link
                onClick={() => backToEmail()}
                data-attr="auth-use-different-email"
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
            >
                ← Use a different email
            </Link>
        </p>
    )
}
