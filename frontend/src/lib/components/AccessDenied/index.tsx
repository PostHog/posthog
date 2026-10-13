import { useActions } from 'kea'
import { ReactNode } from 'react'

import * as stampDenied from '@posthog/brand/hoggies/png/stamp-denied'

import { pngHoggie } from 'lib/brand/hoggies'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

import { supportLogic } from '../Support/supportLogic'

const HedgehogStampDenied = pngHoggie(stampDenied)

export interface AccessDeniedProps {
    /** Name of the object the user can't access (e.g. "feature flag"). Produces: "You do not have access to this {object}...". */
    object?: string
    /** Custom explanation of *why* access is denied. Rendered in place of the default first sentence; the support-link tail stays. */
    reason?: ReactNode
    inline?: boolean
}

export function AccessDenied({ object, reason, inline = false }: AccessDeniedProps): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    const handleClickSupport = (): void => {
        openSupportForm({ kind: 'support' })
    }

    return (
        <div className={cn('flex flex-col items-center max-w-2xl p-4 mx-auto text-center', !inline && 'my-24')}>
            <HedgehogStampDenied className={inline ? 'w-32 h-32' : 'w-64 h-64'} />
            <h1 className="text-3xl font-bold mt-4 mb-0">Access denied</h1>
            {reason ? (
                <>
                    <p className="text-sm mt-3 mb-0">{reason}</p>
                    <p className="text-sm mt-2 mb-0">
                        Please contact your account's administrators or{' '}
                        <Link onClick={handleClickSupport}>support</Link> if you think this is a mistake.
                    </p>
                </>
            ) : object ? (
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
