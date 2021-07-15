import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { Link } from '../Link'
import './NotFound.scss'

interface NotFoundProps {
    object: string // Type of object that was not found (e.g. `dashboard`, `insight`, `action`, ...)
}

export function NotFound({ object }: NotFoundProps): JSX.Element {
    return (
        <div className="not-found-component">
            <div className="graphic" />
            <h1 className="page-title">{capitalizeFirstLetter(object)} not found</h1>
            <b>It seems this page may have been lost in space.</b>
            <p>
                It’s possible this {object} may have been deleted or its sharing settings changed. Please check with the
                person who sent you here, or{' '}
                <Link
                    to={`https://posthog.com/support?utm_medium=in-product&utm_campaign=${object}-not-found`}
                    target="_blank"
                    rel="noopener"
                >
                    contact support
                </Link>{' '}
                if you think this is a mistake.
            </p>
        </div>
    )
}
