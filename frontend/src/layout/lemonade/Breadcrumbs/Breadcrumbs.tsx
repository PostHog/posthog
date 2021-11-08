import { useValues } from 'kea'
import React from 'react'
import { IconExpandMore } from '../../../lib/components/icons'
import { Link } from '../../../lib/components/Link'
import './Breadcrumbs.scss'
import { Breadcrumb, breadcrumbsLogic } from './breadcrumbsLogic'
import { Tooltip } from '../../../lib/components/Tooltip'

function Breadcrumb({ breadcrumb }: { breadcrumb: Breadcrumb }): JSX.Element {
    let breadcrumbContent = (
        <div className="Breadcrumbs__breadcrumb">
            {breadcrumb.symbol}
            {breadcrumb.name}
        </div>
    )
    if (breadcrumb.path) {
        breadcrumbContent = <Link to={breadcrumb.path}>{breadcrumbContent}</Link>
    }
    return (
        <Tooltip title={breadcrumb.tooltip || (breadcrumb.path ? `Go to ${breadcrumb.name}` : null)}>
            {breadcrumbContent}
        </Tooltip>
    )
}

export function Breadcrumbs(): JSX.Element | false {
    const { breadcrumbs } = useValues(breadcrumbsLogic)

    return (
        breadcrumbs.length > 0 && (
            <div className="Breadcrumbs">
                <Breadcrumb breadcrumb={breadcrumbs[0]} />
                {breadcrumbs.slice(1).map((breadcrumb) => (
                    <React.Fragment key={breadcrumb.name}>
                        <IconExpandMore className="Breadcrumbs__separator" />
                        <Breadcrumb breadcrumb={breadcrumb} />
                    </React.Fragment>
                ))}
            </div>
        )
    )
}
