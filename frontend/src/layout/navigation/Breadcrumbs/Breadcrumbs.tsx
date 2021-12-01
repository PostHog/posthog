import React, { useState } from 'react'
import { useValues } from 'kea'
import { IconArrowDropDown, IconChevronRight } from 'lib/components/icons'
import { Link } from 'lib/components/Link'
import './Breadcrumbs.scss'
import { breadcrumbsLogic } from './breadcrumbsLogic'
import { Breadcrumb as IBreadcrumb } from '~/types'
import clsx from 'clsx'
import { Popup } from 'lib/components/Popup/Popup'

function Breadcrumb({ breadcrumb }: { breadcrumb: IBreadcrumb }): JSX.Element {
    const [popoverShown, setPopoverShown] = useState(false)

    let breadcrumbContent = (
        <div
            className={clsx(
                'Breadcrumbs__breadcrumb',
                breadcrumb.here && 'Breadcrumbs__breadcrumb--current',
                (breadcrumb.path || breadcrumb.popup) && 'Breadcrumbs__breadcrumb--actionable'
            )}
            onClick={() => breadcrumb.popup && setPopoverShown(!popoverShown)}
        >
            {breadcrumb.symbol}
            {breadcrumb.name}
            {breadcrumb.popup && (
                <IconArrowDropDown
                    style={{ color: 'var(--muted-alt)', marginLeft: 4, marginRight: 0, fontSize: '1.2em' }}
                />
            )}
        </div>
    )

    if (breadcrumb.path) {
        breadcrumbContent = <Link to={breadcrumb.path}>{breadcrumbContent}</Link>
    }

    if (breadcrumb.popup) {
        return (
            <Popup {...breadcrumb.popup} visible={popoverShown} onClickOutside={() => setPopoverShown(false)}>
                {breadcrumbContent}
            </Popup>
        )
    }

    return breadcrumbContent
}

export function Breadcrumbs(): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)

    return breadcrumbs.length > 0 ? (
        <div className="Breadcrumbs">
            <Breadcrumb breadcrumb={breadcrumbs[0]} />
            {breadcrumbs.slice(1).map((breadcrumb, index) => (
                <React.Fragment key={breadcrumb.name || '…'}>
                    <IconChevronRight className="Breadcrumbs__separator" />
                    <Breadcrumb
                        breadcrumb={
                            index === breadcrumbs.length - 2
                                ? { ...breadcrumb, path: undefined, here: true }
                                : breadcrumb
                        }
                    />
                </React.Fragment>
            ))}
        </div>
    ) : null
}
