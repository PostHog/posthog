import { capitalizeFirstLetter } from 'lib/utils'
import { Link } from 'lib/lemon-ui/Link'
import './NotFound.scss'

interface NotFoundProps {
    object: string // Type of object that was not found (e.g. `dashboard`, `insight`, `action`, ...)
    caption?: React.ReactNode
}

export function NotFound({ object, caption }: NotFoundProps): JSX.Element {
    return (
        <div className="NotFoundComponent space-y-2">
            <div className="NotFoundComponent__graphic" />
            <h1>{capitalizeFirstLetter(object)} not found</h1>
            <p>
                <b>It seems this page may have been lost in space.</b>
            </p>
            <p>
                {caption || (
                    <>
                        It's possible this {object} may have been deleted or its sharing settings changed. Please check
                        with the person who sent you here, or{' '}
                        <Link
                            to={`https://posthog.com/support?utm_medium=in-product&utm_campaign=${object}-not-found`}
                            target="_blank"
                        >
                            contact support
                        </Link>{' '}
                        if you think this is a mistake.
                    </>
                )}
            </p>
        </div>
    )
}
