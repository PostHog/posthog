import React, { useState } from 'react'
import { useValues } from 'kea'
import { IconArrowDropDown, IconEllipsisVertical } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import './Breadcrumbs.scss'
import { Breadcrumb as IBreadcrumb } from '~/types'
import clsx from 'clsx'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { NewInsightButton } from 'scenes/saved-insights/SavedInsights'

/**
 * In PostHog 3000 breadcrumbs also serve as the top bar. This is marked by theses two features:
 * - The "More scene actions" button (vertical ellipsis)
 * - The "Quick scene actions" buttons (zero or more buttons on the right)
 */
export function Breadcrumbs(): JSX.Element | null {
    const { firstBreadcrumb, tailBreadcrumbs } = useValues(breadcrumbsLogic)

    return firstBreadcrumb ? (
        <div className="Breadcrumbs3000">
            <Breadcrumb breadcrumb={firstBreadcrumb} index={0} />
            {tailBreadcrumbs.map((breadcrumb, index) => (
                <React.Fragment key={breadcrumb.name || '…'}>
                    <div className="Breadcrumbs3000__separator" />
                    <Breadcrumb breadcrumb={breadcrumb} index={index + 1} here={index === tailBreadcrumbs.length - 1} />
                </React.Fragment>
            ))}
            {/* TODO: These buttons below are hardcoded right now, scene-based system coming in the next PR */}
            <LemonButton className="Breadcrumbs3000__more" icon={<IconEllipsisVertical />} size="small" />
            <div className="Breadcrumbs3000__actions">
                <NewInsightButton dataAttr="project-home-new-insight" />
            </div>
        </div>
    ) : null
}

interface BreadcrumbProps {
    breadcrumb: IBreadcrumb
    index: number
    here?: boolean
}

function Breadcrumb({ breadcrumb, index, here }: BreadcrumbProps): JSX.Element {
    const [popoverShown, setPopoverShown] = useState(false)

    const Component = breadcrumb.path ? Link : 'div'
    const breadcrumbContent = (
        <Component
            className={clsx(
                'Breadcrumbs3000__breadcrumb',
                (breadcrumb.path || breadcrumb.popover) && 'Breadcrumbs3000__breadcrumb--actionable',
                here && 'Breadcrumbs3000__breadcrumb--here'
            )}
            onClick={() => {
                breadcrumb.popover && setPopoverShown(!popoverShown)
            }}
            data-attr={`breadcrumb-${index}`}
            to={breadcrumb.path}
        >
            {breadcrumb.symbol}
            <span>{breadcrumb.name}</span>
            {breadcrumb.popover && <IconArrowDropDown />}
        </Component>
    )

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
