import { getItemTypeDisplayName } from 'lib/components/Search/searchItemDisplay'
import { SearchItem } from 'lib/components/Search/searchItems'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { pluralTypeName } from './commandKFilterOptions'
import { RankKey, compareRanks, rankLocalItem, searchWords, tokenTypos } from './commandKRanking'
import type { CommandKRow, CommandKSection } from './commandKSections'

const BEST_MATCHES_LIMIT = 3
const GROUP_LIMIT = 3
const FLAT_LIST_LIMIT = 8

interface RankedItem {
    item: SearchItem
    rank: RankKey
    groupKey: string
}

const groupKeyFor = (item: SearchItem): string =>
    item.category === 'results' ? String(item.record?.type ?? item.itemType ?? 'other') : item.category

function groupLabel(groupKey: string): string {
    if (groupKey === 'products') {
        return 'Products'
    }
    return capitalizeFirstLetter(pluralTypeName(getItemTypeDisplayName(groupKey) ?? groupKey.replace(/_/g, ' ')))
}

function rankProducts(products: SearchItem[], query: string): RankedItem[] {
    return products.flatMap((item) => {
        const ranked = rankLocalItem(query, String(item.displayName || item.name), item.searchKeywords)
        return ranked
            ? [
                  {
                      item: ranked.matchedAlias ? { ...item, matchedSearchKeyword: ranked.matchedAlias } : item,
                      rank: ranked.rank,
                      groupKey: 'products',
                  },
              ]
            : []
    })
}

const itemRow = (
    section: string,
    item: SearchItem,
    highlightWords: string[],
    duplicates = 0,
    showCreator = false,
    showType = section === 'best-matches'
): CommandKRow => ({
    kind: 'item',
    key: `${section}/${item.id}`,
    item,
    section: item.category === 'results' ? 'results' : 'products',
    highlightWords,
    ranked: true,
    showType,
    ...(duplicates ? { duplicates } : {}),
    ...(showCreator ? { showCreator } : {}),
})

const normalizedName = (item: SearchItem): string =>
    String(item.displayName || item.name)
        .toLowerCase()
        .replace(/\s*\((copy|duplicate)( \d+)?\)\s*$/, '')
        .replace(/\s+/g, ' ')
        .trim()

interface CollapsedItem extends RankedItem {
    duplicates: number
}

function collapseSameName(entries: RankedItem[]): CollapsedItem[] {
    const byName = new Map<string, CollapsedItem>()
    const collapsed: CollapsedItem[] = []
    for (const entry of entries) {
        const key = `${entry.groupKey}|${normalizedName(entry.item)}`
        const existing = byName.get(key)
        if (existing) {
            existing.duplicates++
            continue
        }
        const kept = { ...entry, duplicates: 0 }
        byName.set(key, kept)
        collapsed.push(kept)
    }
    return collapsed
}

function noticeSection(
    match: SearchItem['searchMatch'],
    words: string[],
    shown: { allWords: boolean; withTypos: boolean },
    state: CommandKSection['state']
): CommandKSection[] {
    if (!match || !words.length) {
        return []
    }
    const missing = words.filter((word) => !match.matchedWords.includes(word))
    const reason =
        !match.matchedAllWords && !shown.allWords && missing.length > 0
            ? 'partial'
            : match.withTypos && shown.withTypos
              ? 'typos'
              : null
    if (!reason) {
        return []
    }
    return [
        {
            key: 'notice',
            label: '',
            rows: [
                {
                    kind: 'notice',
                    key: `notice/${reason}`,
                    reason,
                    missing: reason === 'partial' ? missing : words,
                    shown: match.matchedWords,
                },
            ],
            state,
        },
    ]
}

interface RankedResultsInput {
    query: string
    highlightWords: string[]
    results: SearchItem[]
    products: SearchItem[]
    state: CommandKSection['state']
    scoped: boolean
}

export function buildRankedResults({
    query,
    highlightWords,
    results,
    products,
    state,
    scoped,
}: RankedResultsInput): CommandKSection[] {
    const candidates: RankedItem[] = [
        ...results.map((item) => ({ item, rank: item.rankKey ?? [], groupKey: groupKeyFor(item) })),
        ...rankProducts(products, query),
    ].sort((a, b) => compareRanks(a.rank, b.rank))
    if (!candidates.length) {
        return []
    }
    const queryWords = searchWords(query)
    const capped = !!results[0]?.searchMatch?.countsCapped
    const mostWordsMatched = candidates[0].rank[0]
    const fullest = candidates.filter((entry) => entry.rank[0] === mostWordsMatched)
    const fewestTypos = Math.min(...fullest.map((entry) => entry.rank[1]))
    const matching = fullest.filter((entry) => entry.rank[1] === fewestTypos)
    const notices =
        state === 'stale'
            ? []
            : noticeSection(
                  results[0]?.searchMatch,
                  highlightWords,
                  { allWords: -mostWordsMatched >= new Set(queryWords).size, withTypos: fewestTypos > 0 },
                  state
              )
    if (scoped) {
        const nameCounts = new Map<string, number>()
        for (const entry of matching) {
            nameCounts.set(normalizedName(entry.item), (nameCounts.get(normalizedName(entry.item)) ?? 0) + 1)
        }
        return [
            ...notices,
            {
                key: 'results',
                label: 'Results',
                rows: matching.map((entry) =>
                    itemRow(
                        'results',
                        entry.item,
                        highlightWords,
                        0,
                        (nameCounts.get(normalizedName(entry.item)) ?? 0) > 1
                    )
                ),
                state,
            },
        ]
    }
    const pool = collapseSameName(matching)
    const groupCount = new Set(pool.map((entry) => entry.groupKey)).size
    if (pool.length <= FLAT_LIST_LIMIT || groupCount === 1) {
        return [
            ...notices,
            {
                key: 'best-matches',
                label: 'Results',
                rows: pool.map((entry) =>
                    itemRow('flat', entry.item, highlightWords, entry.duplicates, entry.duplicates > 0, groupCount > 1)
                ),
                state,
            },
        ]
    }
    const best: CollapsedItem[] = []
    const seenGroups = new Set<string>()
    for (const entry of pool) {
        if (best.length === BEST_MATCHES_LIMIT) {
            break
        }
        if (!seenGroups.has(entry.groupKey)) {
            best.push(entry)
            seenGroups.add(entry.groupKey)
        }
    }
    const groups = new Map<string, CollapsedItem[]>()
    for (const entry of pool) {
        if (best.includes(entry)) {
            continue
        }
        groups.set(entry.groupKey, [...(groups.get(entry.groupKey) ?? []), entry])
    }
    for (const entry of best) {
        if (!groups.has(entry.groupKey)) {
            groups.set(entry.groupKey, [])
        }
    }
    const sections: CommandKSection[] = [
        ...notices,
        {
            key: 'best-matches',
            label: 'Best matches',
            rows: best.map((entry) =>
                itemRow('best-matches', entry.item, highlightWords, entry.duplicates, entry.duplicates > 0)
            ),
            state,
        },
    ]
    const typeIntent = (groupKey: string): boolean =>
        queryWords.length === 1 &&
        queryWords[0].length >= 3 &&
        groupKey !== 'products' &&
        searchWords(groupLabel(groupKey)).some((word) => tokenTypos(queryWords[0], word) !== null)
    const orderedGroups = [...groups].sort(([a], [b]) => Number(typeIntent(b)) - Number(typeIntent(a)))
    for (const [groupKey, entries] of orderedGroups) {
        const shown = entries.slice(0, GROUP_LIMIT)
        const inBest = best.filter((entry) => entry.groupKey === groupKey)
        const sample = entries[0] ?? inBest[0]
        const total = Math.max(sample.item.searchMatch?.typeCount ?? 0, entries.length + inBest.length)
        const rows: CommandKRow[] = shown.map((entry) =>
            itemRow(`group-${groupKey}`, entry.item, highlightWords, entry.duplicates, entry.duplicates > 0)
        )
        const covered = inBest.length + shown.reduce((sum, entry) => sum + 1 + entry.duplicates, 0)
        if (groupKey !== 'products' && total > covered) {
            rows.push({
                kind: 'scope',
                key: `group-${groupKey}/see-all`,
                type: groupKey,
                label: capped
                    ? `See all ${groupLabel(groupKey).toLowerCase()}`
                    : `See all ${total.toLocaleString()} ${groupLabel(groupKey).toLowerCase()}`,
            })
        }
        if (!rows.length) {
            continue
        }
        sections.push({
            key: `group-${groupKey}`,
            label: groupLabel(groupKey),
            count: total,
            countIsLowerBound: capped && groupKey !== 'products',
            rows,
            state,
        })
    }
    return sections
}
