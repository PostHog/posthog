import { IconBug } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'
import { ExceptionAttributes } from 'lib/components/Errors/types'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { Children } from 'react'
import { match } from 'ts-pattern'

export interface ExceptionAttributesPreviewProps {
    attributes: ExceptionAttributes | null
    loading: boolean
}

export function ExceptionAttributesPreview({ attributes, loading }: ExceptionAttributesPreviewProps): JSX.Element {
    return (
        <span className="flex items-center gap-1 text-muted group-hover:text-brand-red">
            {match(loading)
                .with(true, () => (
                    <span className="text-muted space-x-2 text-xs">
                        <Spinner />
                        <span>Loading details...</span>
                    </span>
                ))
                .with(
                    false,
                    () =>
                        attributes && (
                            <div className="flex items-center gap-2">
                                <PropertyWrapper title="Unhandled" visible={!attributes.handled}>
                                    <IconBug className="text-sm text-secondary" />
                                </PropertyWrapper>
                                <PropertyWrapper title={attributes.browser} visible={!!attributes.browser}>
                                    <PropertyIcon
                                        property="$browser"
                                        value={attributes.browser}
                                        className="text-sm text-secondary"
                                    />
                                </PropertyWrapper>
                                <PropertyWrapper title={attributes.os} visible={!!attributes.os}>
                                    <PropertyIcon
                                        property="$os"
                                        value={attributes.os}
                                        className="text-sm text-secondary"
                                    />
                                </PropertyWrapper>
                            </div>
                        )
                )
                .exhaustive()}
        </span>
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
