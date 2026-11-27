import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconOpenSidebar } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const HedgehogReadingIsMagic = pngHoggie(readingIsMagicPng)

/** The quill "no ingestion warnings" screen that both ingestion warnings pages show when nothing went wrong. */
export function QuillIngestionWarningsIntro({
    title,
    eventsDataAttr,
}: {
    title: string
    eventsDataAttr: string
}): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <EmptyMedia>
                    <HedgehogReadingIsMagic className="w-40" />
                </EmptyMedia>
                <EmptyTitle>{title}</EmptyTitle>
                <EmptyDescription>
                    Your incoming events look clean. If we detect any issues with your data, we'll show them here.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row justify-center">
                <Button
                    variant="primary"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.eventDefinitions()} />}
                    data-attr={eventsDataAttr}
                >
                    Explore your events
                    <IconOpenSidebar />
                </Button>
                <Button
                    variant="outline"
                    nativeButton={false}
                    render={
                        <LinkPrimitive
                            to="https://posthog.com/docs/data/data-management#ingestion-warnings?utm_medium=in-product&utm_campaign=empty-state-docs-link"
                            target="_blank"
                        />
                    }
                    data-attr="product-introduction-docs-link"
                >
                    Learn more
                    <IconOpenSidebar />
                </Button>
            </EmptyContent>
        </Empty>
    )
}
