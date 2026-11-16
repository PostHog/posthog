import clsx from 'clsx'

import { CardDescription, CardTitle, Spinner } from '@posthog/quill'

import { QuillCardMeta } from 'lib/components/Cards/QuillCardMeta'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { WidgetCardHeaderDescription } from './WidgetCardHeader'

export type QuillWidgetCardHeaderProps = {
    title: string
    defaultTitle?: string
    titleHref?: string
    topHeading: JSX.Element
    description?: string
    showDescription?: boolean
    loading?: boolean
    refreshControl?: JSX.Element | null
    menuItems?: JSX.Element | null
}

export function QuillWidgetCardHeader({
    title,
    defaultTitle,
    titleHref,
    topHeading,
    description,
    showDescription,
    loading,
    refreshControl,
    menuItems,
}: QuillWidgetCardHeaderProps): JSX.Element {
    const displayTitle = title || defaultTitle || 'Untitled'
    const titleContent = (
        <>
            <span className="truncate">{displayTitle}</span>
            {loading && (
                <span className="ml-1.5 inline-flex items-center gap-1.5 text-sm font-medium text-accent">
                    <Spinner />
                    <span>Loading</span>
                </span>
            )}
        </>
    )

    return (
        <QuillCardMeta
            topHeading={topHeading}
            refreshControl={refreshControl}
            menuItems={menuItems}
            content={
                <>
                    <CardTitle
                        role="heading"
                        aria-level={4}
                        title={displayTitle}
                        data-attr="widget-card-title"
                        className={clsx('flex min-h-7 min-w-0 items-center', titleHref && 'overflow-visible')}
                    >
                        {titleHref ? (
                            <LinkPrimitive to={titleHref} className="max-w-full truncate text-foreground">
                                {titleContent}
                            </LinkPrimitive>
                        ) : (
                            titleContent
                        )}
                    </CardTitle>
                    {showDescription !== false && !!description && (
                        <CardDescription className="leading-4">
                            <WidgetCardHeaderDescription description={description} />
                        </CardDescription>
                    )}
                </>
            }
        />
    )
}
