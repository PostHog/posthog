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
        <div className="mx-auto my-24 flex max-w-2xl flex-col items-center p-4 text-center">
            <img src={noAccessNopehog} alt="Access denied illustration" className="h-64 w-64 bg-center bg-no-repeat" />
            <h1 className="mb-0 mt-4 text-3xl font-bold">Access denied</h1>
            {object ? (
                <p className="mb-0 mt-3 text-sm">
                    You do not have access to this {object}. Please contact the creator of this {object} or{' '}
                    <Link onClick={handleClickSupport}>support</Link> if you think this is a mistake.
                </p>
            ) : (
                <p className="mb-0 mt-3 text-sm">
                    You do not have access to this resource. Please contact the creator of this resource or{' '}
                    <Link onClick={handleClickSupport}>support</Link> if you think this is a mistake.
                </p>
            )}
        </div>
    )
}
