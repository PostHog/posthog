import { Fragment } from 'react'

import { Link } from 'lib/lemon-ui/Link'

import { LemonBanner } from '../../lemon-ui/LemonBanner'
import type { Finding } from './types'

export function HogSenseBanner({ finding, className }: { finding: Finding; className?: string }): JSX.Element {
    const bannerType = finding.severity === 'error' ? 'error' : finding.severity
    return (
        <LemonBanner type={bannerType} className={className}>
            {finding.description}
            {finding.docs?.map((doc) => (
                <Fragment key={doc.url}>
                    {' '}
                    <Link to={doc.url} target="_blank">
                        {doc.label}
                    </Link>
                </Fragment>
            ))}
        </LemonBanner>
    )
}
