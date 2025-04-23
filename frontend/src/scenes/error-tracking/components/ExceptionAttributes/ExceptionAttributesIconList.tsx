import { LemonTag } from '@posthog/lemon-ui'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { IconFire } from 'lib/lemon-ui/icons'
import { Children, cloneElement } from 'react'
import { ExceptionAttributes } from 'scenes/error-tracking/utils'

export interface ExceptionAttributesIconListProps {
    attributes: ExceptionAttributes
}

export function ExceptionAttributesIconList({ attributes }: ExceptionAttributesIconListProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <PropertyWrapper title="Unhandled" visible={!attributes.handled}>
                <IconFire color="red" />
            </PropertyWrapper>
            <PropertyWrapper title={attributes.browser} visible={!!attributes.browser}>
                <PropertyIcon property="$browser" value={attributes.browser} />
            </PropertyWrapper>
            <PropertyWrapper title={attributes.os} visible={!!attributes.os}>
                <PropertyIcon property="$os" value={attributes.os} />
            </PropertyWrapper>
        </div>
    )
}

export function PropertyWrapper({
    title,
    visible = true,
    children,
}: {
    title?: string
    visible?: boolean
    children: JSX.Element
}): JSX.Element {
    if (Children.count(children) == 0 || title === undefined || !visible) {
        return <></>
    }
    return (
        <LemonTag>
            {cloneElement(children, { ...children.props, className: 'text-sm text-secondary' })}{' '}
            <span className="capitalize">{title}</span>
        </LemonTag>
    )
}
