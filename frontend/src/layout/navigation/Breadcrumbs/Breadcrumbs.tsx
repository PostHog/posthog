import './Breadcrumbs.scss'

import { IconChevronDown } from '@posthog/icons'
import clsx from 'clsx'
import { useValues } from 'kea'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import React, { useState } from 'react'

import { Breadcrumb as IBreadcrumb } from '~/types'

import { breadcrumbsLogic } from './breadcrumbsLogic'

function Breadcrumb({ breadcrumb }: { breadcrumb: IBreadcrumb }): JSX.Element {
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
            data-attr={`breadcrumb-${breadcrumb.key}`}
        >
            {breadcrumb.symbol}
            <span>{breadcrumb.name}</span>
            {breadcrumb.popover && <IconChevronDown className="text-muted-alt text-lg" />}
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
            <Breadcrumb breadcrumb={firstBreadcrumb} />
            {tailBreadcrumbs.map((breadcrumb) => (
                <React.Fragment key={breadcrumb.name || '…'}>
                    <IconChevronRight className="Breadcrumbs__separator" />
                    <Breadcrumb breadcrumb={breadcrumb} />
                </React.Fragment>
            ))}
        </div>
    ) : null
}
