import { useActions } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import noAccessNopehog from 'public/no-access-nopehog.png'

import { supportLogic } from '../Support/supportLogic'

export interface AccessDeniedProps {
    object?: string
}

export function AccessDenied({ object }: AccessDeniedProps): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    const handleClickSupport = (): void => {
        openSupportForm({ kind: 'support' })
    }

    return (
        <div className="flex flex-col items-center max-w-2xl p-4 my-24 mx-auto text-center">
            <img src={noAccessNopehog} alt="Access denied illustration" className="w-64 h-64 bg-no-repeat bg-center" />
            <h1 className="text-3xl font-bold mt-4 mb-0">Access denied</h1>
            {object ? (
                <p className="text-sm mt-3 mb-0">
                    You do not have access to this {object}. Please contact the creator of this {object} or{' '}
                    <Link onClick={handleClickSupport}>support</Link> if you think this is a mistake.
                </p>
            ) : (
                <p className="text-sm mt-3 mb-0">
                    You do not have access to this page. Please contact your account's administrators or{' '}
                    <Link onClick={handleClickSupport}>support</Link> if you think this is a mistake.
                </p>
            )}
        </div>
    )
}
