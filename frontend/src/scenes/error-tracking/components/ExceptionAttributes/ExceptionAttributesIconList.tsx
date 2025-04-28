import { IconBug } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { Children } from 'react'
import { ExceptionAttributes } from 'scenes/error-tracking/utils'

export interface ExceptionAttributesIconListProps {
    attributes: ExceptionAttributes
}

export function ExceptionAttributesIconList({ attributes }: ExceptionAttributesIconListProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <PropertyWrapper title="Unhandled" visible={!attributes.handled}>
                <IconBug className="text-sm text-secondary" />
            </PropertyWrapper>
            <PropertyWrapper title={attributes.browser} visible={!!attributes.browser}>
                <PropertyIcon property="$browser" value={attributes.browser} className="text-sm text-secondary" />
            </PropertyWrapper>
            <PropertyWrapper title={attributes.os} visible={!!attributes.os}>
                <PropertyIcon property="$os" value={attributes.os} className="text-sm text-secondary" />
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
            {children}
            <span className="capitalize">{title}</span>
        </LemonTag>
    )
}
