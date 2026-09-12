import { Fragment } from 'react'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { UsageReductionOption } from './billing-utils'

/**
 * The way out of a usage limit that does not cost more money.
 */
export function UsageReductionHint({ options }: { options: UsageReductionOption[] }): JSX.Element {
    return (
        <span>
            To stay inside your limit, check your{' '}
            <Link to={urls.organizationBillingSection('spend')} data-attr="usage-reduction-spend-breakdown">
                spend breakdown
            </Link>
            {options.map((option, index) => (
                <Fragment key={option.to}>
                    {index === options.length - 1 ? ' or ' : ', '}
                    <Link to={option.to} data-attr="usage-reduction-option">
                        {option.text}
                    </Link>
                </Fragment>
            ))}
            .
        </span>
    )
}
