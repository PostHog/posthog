import { getIconForItem, getItemTypeDisplayName } from 'lib/components/Search/searchItemDisplay'
import { SearchItem } from 'lib/components/Search/searchItems'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { highlightSegments } from './commandKRanking'
import { CommandKSearchTime } from './CommandKSearchTime'
import { CommandKRow } from './commandKSections'

const userFolder = (item: SearchItem): string | null => {
    const segments = splitPath(String(item.record?.path ?? '')).slice(0, -1)
    return segments.length === 0 || segments[0] === 'Unfiled' ? null : segments.join(' › ')
}

function rankedContext(
    item: SearchItem,
    showCreator: boolean
): { detail: string | null; tail: JSX.Element | string | null } {
    if (item.category !== 'results') {
        return {
            detail: item.parentName ? `in ${item.parentName}` : null,
            tail: item.matchedSearchKeyword ? `Matches "${item.matchedSearchKeyword}"` : null,
        }
    }
    const age = item.lastViewedAt ? (
        <CommandKSearchTime time={item.lastViewedAt} prefix="viewed" tooltipLabel="Last used" />
    ) : item.record?.created_at ? (
        <CommandKSearchTime time={String(item.record.created_at)} prefix="created" tooltipLabel="Created" />
    ) : null
    const detail = [userFolder(item), showCreator ? item.createdByName : null].filter(Boolean).join(' · ')
    return { detail: detail || null, tail: age }
}

export function CommandKSearchRankedItem({ row }: { row: Extract<CommandKRow, { kind: 'item' }> }): JSX.Element {
    const { item } = row
    const typeLabel = !row.showType
        ? null
        : item.category === 'results'
          ? getItemTypeDisplayName(item.itemType)
          : item.category === 'persons'
            ? 'Person'
            : item.category === 'settings'
              ? 'Setting'
              : item.category === 'accounts'
                ? 'Account'
                : 'Product'
    const context = rankedContext(item, !!row.showCreator)
    return (
        <>
            {getIconForItem(item)}
            <span className="truncate" translate="no">
                {highlightSegments(String(item.displayName || item.name), row.highlightWords ?? []).map(
                    (segment, index) =>
                        segment.match ? (
                            <span key={index} className="font-semibold">
                                {segment.text}
                            </span>
                        ) : (
                            segment.text
                        )
                )}
            </span>
            {typeLabel && (
                <span className="shrink-0 text-xs text-muted-foreground">{capitalizeFirstLetter(typeLabel)}</span>
            )}
            {row.duplicates ? (
                <span
                    className="shrink-0 rounded-sm border border-input px-1 text-xxs text-muted-foreground"
                    title="Items with the same name are combined. Open the type to see them all."
                >
                    {`+${row.duplicates} with this name`}
                </span>
            ) : null}
            {(context.detail || context.tail) && (
                <span className="ml-auto flex max-w-1/2 shrink-0 items-center gap-1 whitespace-nowrap pl-2 text-xs text-muted-foreground">
                    {context.detail && <span className="min-w-0 truncate">{context.detail}</span>}
                    {context.detail && context.tail && <span className="shrink-0">·</span>}
                    {context.tail && <span className="shrink-0">{context.tail}</span>}
                </span>
            )}
        </>
    )
}
