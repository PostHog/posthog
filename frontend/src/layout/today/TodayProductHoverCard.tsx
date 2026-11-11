import { IconExternal } from '@posthog/icons'
import { Button, Item, ItemContent, ItemSeparator, ItemTitle, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { NavProductIcon } from '~/layout/panel-layout/navbar/tabs/NavProductIcon'

import { TodayExplainerPreview, TodayProductPreview } from './todayPreviewCards'

export function TodayProductHoverCard({
    preview,
    onAction,
}: {
    preview: TodayProductPreview | TodayExplainerPreview
    onAction: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col" data-attr="today-product-hover-card">
            <Item size="xs" className="items-start">
                <ItemContent className="min-w-0 gap-2">
                    <ItemTitle className="flex items-center gap-2 overflow-visible wrap-anywhere">
                        <span
                            className="TodayIconBadge flex size-4 shrink-0 items-center justify-center group/colorful-product-icons colorful-product-icons-true [&_svg]:size-4"
                            aria-hidden
                        >
                            {preview.kind === 'product' ? <NavProductIcon item={preview.product} /> : preview.icon}
                        </span>
                        <span className="min-w-0 flex-1 font-semibold">{preview.label}</span>
                    </ItemTitle>
                    <div className="flex flex-col gap-2 pl-6">
                        {preview.description && <p className="m-0 text-xs">{preview.description}</p>}
                        {preview.example && (
                            <div className="flex flex-col gap-0.5">
                                <Text size="xs" variant="muted" className="font-semibold">
                                    For example
                                </Text>
                                <Text size="xs" variant="muted">
                                    {preview.example}
                                </Text>
                            </div>
                        )}
                    </div>
                </ItemContent>
            </Item>
            {preview.docsHref && (
                <>
                    <ItemSeparator className="my-0" />
                    <div className="flex flex-col p-1">
                        <Button
                            left
                            className="w-full"
                            render={<LinkPrimitive to={preview.docsHref} target="_blank" />}
                            onClick={onAction}
                            data-attr="today-product-card-docs"
                        >
                            <IconExternal />
                            Read the docs
                        </Button>
                    </div>
                </>
            )}
        </div>
    )
}
