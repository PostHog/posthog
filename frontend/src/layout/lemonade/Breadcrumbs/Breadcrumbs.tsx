import { useValues } from 'kea'
import React from 'react'
import { IconExpandMore } from 'lib/components/icons'
import { Link } from 'lib/components/Link'
import './Breadcrumbs.scss'
import { Breadcrumb as IBreadcrumb, breadcrumbsLogic } from './breadcrumbsLogic'
import clsx from 'clsx'
import { Skeleton } from 'antd'

function Breadcrumb({ breadcrumb }: { breadcrumb: IBreadcrumb }): JSX.Element {
    let breadcrumbContent = (
        <div className={clsx('Breadcrumbs__breadcrumb', breadcrumb.here && 'Breadcrumbs__breadcrumb--current')}>
            {breadcrumb.symbol}
            {breadcrumb.name}
        </div>
    )
    if (breadcrumb.path) {
        breadcrumbContent = <Link to={breadcrumb.path}>{breadcrumbContent}</Link>
    }
    return breadcrumbContent
}

export function Breadcrumbs(): JSX.Element | null {
    const { breadcrumbs, breadcrumbsLoading } = useValues(breadcrumbsLogic)

    return breadcrumbsLoading || breadcrumbs.length > 0 ? (
        <div className={clsx('Breadcrumbs', breadcrumbsLoading && 'Breadcrumbs--loading')}>
            {breadcrumbsLoading ? (
                <Skeleton active paragraph={false} title={{ width: 320 }} />
            ) : (
                <>
                    <Breadcrumb breadcrumb={breadcrumbs[0]} />
                    {breadcrumbs.slice(1).map((breadcrumb) => (
                        <React.Fragment key={breadcrumb.name || '…'}>
                            <IconExpandMore className="Breadcrumbs__separator" />
                            <Breadcrumb breadcrumb={breadcrumb} />
                        </React.Fragment>
                    ))}
                </>
            )}
        </div>
    ) : null
}
