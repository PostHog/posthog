import { useId } from 'react'

import { IconEye, IconPeople, IconTrash } from '@posthog/icons'
import { Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, Text } from '@posthog/quill'

export interface TranscriptFileNotesProps {
    retentionDays: number
}

export function TranscriptFileNotes({ retentionDays }: TranscriptFileNotesProps): JSX.Element {
    const headingId = useId()

    return (
        <section className="flex flex-col gap-1" aria-labelledby={headingId} data-attr="agent-transcript-file-notes">
            <Text id={headingId} size="xs" weight="medium" variant="muted" render={<h2 className="m-0 px-3" />}>
                What happens to the file
            </Text>
            <ItemGroup combined>
                <Item variant="muted" size="xs">
                    <ItemMedia variant="icon">
                        <IconPeople />
                    </ItemMedia>
                    <ItemContent>
                        <ItemDescription>
                            The PostHog team uses it only to improve setup with AI agents.
                        </ItemDescription>
                    </ItemContent>
                </Item>
                <Item variant="muted" size="xs">
                    <ItemMedia variant="icon">
                        <IconEye />
                    </ItemMedia>
                    <ItemContent>
                        <ItemDescription>PostHog staff review each transcript.</ItemDescription>
                    </ItemContent>
                </Item>
                <Item variant="muted" size="xs">
                    <ItemMedia variant="icon">
                        <IconTrash />
                    </ItemMedia>
                    <ItemContent>
                        <ItemDescription>
                            We delete the file <span translate="no">{retentionDays}</span> days after you upload it.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            </ItemGroup>
        </section>
    )
}
