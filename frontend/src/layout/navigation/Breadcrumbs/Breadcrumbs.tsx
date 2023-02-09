import React, { useState } from 'react'
import { useValues } from 'kea'
import { IconArrowDropDown, IconChevronRight } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import './Breadcrumbs.scss'
import { breadcrumbsLogic } from './breadcrumbsLogic'
import { Breadcrumb as IBreadcrumb } from '~/types'
import clsx from 'clsx'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

function Breadcrumb({ breadcrumb, index }: { breadcrumb: IBreadcrumb; index: number }): JSX.Element {
    const [popoverShown, setPopoverShown] = useState(false)

    let breadcrumbContent = (
        <div
            className={clsx(
                'Breadcrumbs__breadcrumb',
                (breadcrumb.path || breadcrumb.popover) && 'Breadcrumbs__breadcrumb--actionable'
            )}
            onClick={() => {
                breadcrumb.popover && setPopoverShown(!popoverShown)
            }}
            data-attr={`breadcrumb-${index}`}
        >
            {breadcrumb.symbol}
            <span>{breadcrumb.name}</span>
            {breadcrumb.popover && <IconArrowDropDown className="text-muted-alt text-lg" />}
        </div>
    )

    if (breadcrumb.path) {
        breadcrumbContent = <Link to={breadcrumb.path}>{breadcrumbContent}</Link>
    }

    if (breadcrumb.popover) {
        return (
            <Popover
                {...breadcrumb.popover}
                visible={popoverShown}
                onClickOutside={() => {
                    if (popoverShown) {
                        setPopoverShown(false)
                    }
                }}
            >
                {breadcrumbContent}
            </Popover>
        )
    }

    return breadcrumbContent
}

export function Breadcrumbs(): JSX.Element | null {
    const { firstBreadcrumb, tailBreadcrumbs } = useValues(breadcrumbsLogic)

    return firstBreadcrumb ? (
        <div className="Breadcrumbs">
            <Breadcrumb breadcrumb={firstBreadcrumb} index={0} />
            {tailBreadcrumbs.map((breadcrumb, index) => (
                <React.Fragment key={breadcrumb.name || '…'}>
                    <IconChevronRight className="Breadcrumbs__separator" />
                    <Breadcrumb breadcrumb={breadcrumb} index={index + 1} />
                </React.Fragment>
            ))}
        </div>
    ) : null
}
