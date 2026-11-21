import type { ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { Item, ItemContent, ItemMedia, Text } from '@posthog/quill'

export function QuillSlowQuerySuggestions({ steps }: { steps: ReactNode }): JSX.Element {
    return (
        <Item variant="outline" size="sm" className="text-start">
            <ItemMedia variant="icon" aria-hidden>
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0">
                {/* pinned: stories wait on this data-attr value, so do not rename it */}
                <Text size="xs" className="m-0" data-attr="insight-loading-waiting-message">
                    Need to speed things up? Some steps to optimize this query:
                </Text>
                <Text size="xs" className="m-0 list-inside list-disc" render={<ul />}>
                    {steps}
                </Text>
            </ItemContent>
        </Item>
    )
}
