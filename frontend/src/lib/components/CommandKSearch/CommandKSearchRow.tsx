import { useActions } from 'kea'
import { memo } from 'react'

import { IconFilter, IconFolder, IconPerson, IconSparkles } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { getIconForItem, getItemTypeDisplayName } from 'lib/components/Search/searchItemDisplay'
import { formatRelativeTimeShort } from 'lib/components/Search/utils'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { ProductIconWrapper, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { commandKSearchLogic } from './commandKSearchLogic'
import { CommandKRow } from './commandKSections'

export const rowDomId = (key: string): string => `command-k-row-${key.replace(/[^a-zA-Z0-9_-]/g, '_')}`

const SECTIONS_WITH_TYPE_LABEL = new Set(['recents', 'starred', 'results', 'groups'])

function RowContent({ row }: { row: CommandKRow }): JSX.Element | null {
    switch (row.kind) {
        case 'filter-key':
            return (
                <>
                    <IconFilter className="size-4 shrink-0 text-muted-foreground" />
                    <span className="shrink-0 font-semibold">
                        {row.negated ? '-' : ''}
                        {row.filter.key}:
                    </span>
                    <span className="truncate text-muted-foreground">{row.filter.description}</span>
                </>
            )
        case 'filter-value': {
            const icon =
                row.filter.key === 'is' && row.option.iconType ? (
                    <ProductIconWrapper type={row.option.iconType}>
                        {iconForType(row.option.iconType as FileSystemIconType)}
                    </ProductIconWrapper>
                ) : row.filter.key === 'createdBy' ? (
                    <IconPerson className="size-4 shrink-0 text-muted-foreground" />
                ) : row.filter.key === 'in' ? (
                    <IconFolder className="size-4 shrink-0 text-muted-foreground" />
                ) : (
                    <IconFilter className="size-4 shrink-0 text-muted-foreground" />
                )
            return (
                <>
                    {icon}
                    <span className="truncate">
                        {row.filter.key === 'name' ? `Name contains "${row.option.label}"` : row.option.label}
                    </span>
                    {row.filter.key === 'createdBy' && row.option.value !== 'me' && (
                        <span className="truncate text-xs text-muted-foreground">{row.option.value}</span>
                    )}
                </>
            )
        }
        case 'ask-ai':
            return (
                <>
                    <IconSparkles className="size-4 shrink-0 text-primary" />
                    <span className="shrink-0">Ask PostHog AI:</span>
                    <span className="truncate text-muted-foreground">{row.question}</span>
                </>
            )
        case 'item': {
            const { item } = row
            const typeLabel = SECTIONS_WITH_TYPE_LABEL.has(row.section)
                ? item.groupNoun || getItemTypeDisplayName(item.itemType)
                : null
            return (
                <>
                    {getIconForItem(item)}
                    <span className="truncate">{String(item.displayName || item.name)}</span>
                    {typeLabel && (
                        <span className="shrink-0 text-xs text-muted-foreground">
                            {capitalizeFirstLetter(typeLabel)}
                        </span>
                    )}
                    {item.parentName && (
                        <span className="shrink-0 text-xs text-muted-foreground">in {item.parentName}</span>
                    )}
                    {item.productCategory && (
                        <span className="shrink-0 text-xs text-muted-foreground">{item.productCategory}</span>
                    )}
                    {item.matchedSearchKeyword && (
                        <span className="ml-auto truncate text-xxs text-muted-foreground">
                            Matches "{item.matchedSearchKeyword}"
                        </span>
                    )}
                    {item.lastViewedAt && (
                        <span
                            className={cn(
                                'shrink-0 whitespace-nowrap text-xs text-muted-foreground',
                                item.matchedSearchKeyword ? 'ml-2' : 'ml-auto'
                            )}
                        >
                            {formatRelativeTimeShort(item.lastViewedAt)}
                        </span>
                    )}
                </>
            )
        }
        default:
            return null
    }
}

interface CommandKSearchRowProps {
    row: CommandKRow
    highlighted: boolean
}

/** What a row shows, beyond its key. Row objects are rebuilt on every keystroke, but this rarely changes. */
const rowContent = (row: CommandKRow): unknown => {
    switch (row.kind) {
        case 'item':
            return row.item
        case 'filter-value':
            return row.option
        case 'filter-key':
            return row.filter
        case 'ask-ai':
            return row.question
        case 'message':
            return row.text
    }
}

export const CommandKSearchRow = memo(
    CommandKSearchRowInner,
    (prev: CommandKSearchRowProps, next: CommandKSearchRowProps) =>
        prev.highlighted === next.highlighted &&
        prev.row.key === next.row.key &&
        rowContent(prev.row) === rowContent(next.row)
)

function CommandKSearchRowInner({ row, highlighted }: CommandKSearchRowProps): JSX.Element {
    const { activateRow, setHighlightedKey } = useActions(commandKSearchLogic)

    if (row.kind === 'message') {
        return (
            <div className="flex h-8 items-center px-2 text-sm text-muted-foreground" role="presentation">
                <span className="truncate">{row.text}</span>
            </div>
        )
    }

    const disabledReason = row.kind === 'item' ? row.item.disabledReason : undefined

    return (
        <Button
            id={rowDomId(row.key)}
            role="option"
            aria-selected={highlighted}
            aria-disabled={disabledReason ? true : undefined}
            title={disabledReason}
            tabIndex={-1}
            size="row"
            left
            data-attr={`command-k-row-${row.kind}`}
            className={cn(
                'h-8 w-full min-w-0 gap-1.5 [&>*]:min-w-0',
                highlighted && 'bg-fill-selected',
                disabledReason && 'opacity-50 cursor-not-allowed'
            )}
            // Keep focus in the input so typing continues after a click.
            onMouseDown={(event: React.MouseEvent<HTMLButtonElement>) => event.preventDefault()}
            onMouseMove={() => !highlighted && setHighlightedKey(row.key)}
            onClick={(event: React.MouseEvent<HTMLButtonElement>) =>
                activateRow(row, event.metaKey || event.ctrlKey, 'click')
            }
        >
            <span className="flex w-full min-w-0 items-center gap-1.5">
                <RowContent row={row} />
            </span>
        </Button>
    )
}
