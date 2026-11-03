import { IconInfo } from '@posthog/icons'
import { Item, ItemContent, ItemMedia } from '@posthog/quill'

import { CommandKRow } from './commandKSections'

type NoticeRow = Extract<CommandKRow, { kind: 'notice' }>

const Words = ({ words }: { words: string[] }): JSX.Element => (
    <span className="font-medium text-foreground">{words.join(' ')}</span>
)

export function CommandKSearchNotice({ row }: { row: NoticeRow }): JSX.Element {
    return (
        <Item
            size="xs"
            variant="outline"
            className="min-h-8 gap-1.5 rounded-md px-2 py-1.5"
            data-attr={`command-k-notice-${row.reason}`}
            role="status"
        >
            <ItemMedia variant="icon" className="text-muted-foreground">
                <IconInfo className="size-3.5" />
            </ItemMedia>
            <ItemContent className="text-xs text-muted-foreground">
                {row.reason === 'partial' ? (
                    <span>
                        No matches for <Words words={row.missing} />. Showing results for <Words words={row.shown} />.
                    </span>
                ) : (
                    <span>
                        No exact matches for <Words words={row.missing} />. Showing close spellings.
                    </span>
                )}
            </ItemContent>
        </Item>
    )
}
