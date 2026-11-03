import FuseClass from 'fuse.js'
import { type ReactNode, isValidElement } from 'react'

import { createFuse } from 'lib/utils/fuseSearch'

import { Setting, SettingId, SettingLevelId, SettingSection, SettingSectionId } from './types'

// Explicitly avoid "heat" matching "feature flags", but still allowing "heature" to match it
export const FUSE_THRESHOLD = 0.2

const RESULT_LIMIT = 30

// A shorter acronym matches too many titles: "ai" is also "Agent instructions".
const MIN_ACRONYM_LENGTH = 3

export interface SearchIndexEntry {
    settingId: SettingId
    settingTitle: string
    /** The first letter of each title word, so "pak" finds "Personal API keys". */
    titleInitials: string
    sectionId: SettingSectionId
    sectionTitle: string
    level: SettingLevelId
    keywords: string
    sectionKeywords: string
    description: string
}

// Helping kea-typegen navigate the exported default class for Fuse
export interface GlobalSearchFuse extends FuseClass<SearchIndexEntry> {
    // Fuse does not expose its collection, and the acronym match reads every entry.
    entries: readonly SearchIndexEntry[]
}

function collectText(node: ReactNode): string {
    if (typeof node === 'string') {
        return node
    }
    if (typeof node === 'number') {
        return String(node)
    }
    if (Array.isArray(node)) {
        return node.map(collectText).join(' ')
    }
    if (isValidElement(node)) {
        return collectText((node.props as { children?: ReactNode }).children)
    }
    return ''
}

/**
 * The words a title puts on screen. A title is JSX whenever it carries a tag such as "Beta",
 * so reading only string titles drops those settings out of the index and leaves them
 * findable by their hyphen-split id alone. Returns an empty string for a title that renders
 * through a component, because its text is not reachable without rendering it.
 */
export function getTitleText(title: ReactNode): string {
    return collectText(title).replace(/\s+/g, ' ').trim()
}

/** The title a search matches on, falling back to the id for a title with no readable text. */
const indexedTitle = (title: ReactNode, id: string): string => getTitleText(title) || id.replace(/[-]/g, ' ')

const titleInitials = (title: string): string =>
    title
        .split(' ')
        .filter((word) => /^[\p{L}\p{N}]/u.test(word))
        .map((word) => word[0])
        .join('')
        .toLowerCase()

const keywordText = (keywords: string[] | undefined): string => (keywords ?? []).join(' ')

const settingDescription = (setting: Setting): string =>
    setting.searchDescription ?? (typeof setting.description === 'string' ? setting.description : '')

export function buildSettingsSearchIndex(
    sections: SettingSection[],
    isSettingVisible: (setting: Setting) => boolean
): SearchIndexEntry[] {
    const entries: SearchIndexEntry[] = []

    for (const section of sections) {
        if (section.hideFromNavigation) {
            continue
        }

        const sectionTitle = indexedTitle(section.title, section.id)
        const shared = {
            sectionId: section.id,
            sectionTitle,
            level: section.level,
            sectionKeywords: keywordText(section.keywords),
        }

        // A section that is a top-level link (e.g. Billing) has no settings of its own, so the
        // section itself is the only thing a search can land on.
        if (section.settings.length === 0) {
            entries.push({
                ...shared,
                settingId: section.id as SettingId,
                settingTitle: sectionTitle,
                titleInitials: titleInitials(sectionTitle),
                keywords: '',
                description: '',
            })
            continue
        }

        for (const setting of section.settings) {
            if (!isSettingVisible(setting)) {
                continue
            }

            const settingTitle = indexedTitle(setting.title, setting.id)
            entries.push({
                ...shared,
                settingId: setting.id,
                settingTitle,
                titleInitials: titleInitials(settingTitle),
                keywords: keywordText(setting.keywords),
                description: settingDescription(setting),
            })
        }
    }

    return entries
}

export function createSettingsSearchFuse(entries: SearchIndexEntry[]): GlobalSearchFuse {
    const fuse = createFuse(entries, {
        keys: [
            { name: 'settingTitle', weight: 2 },
            { name: 'keywords', weight: 1.5 },
            { name: 'sectionTitle', weight: 1 },
            { name: 'sectionKeywords', weight: 0.75 },
            { name: 'description', weight: 0.5 },
            { name: 'settingId', weight: 0.5 },
        ],
        threshold: FUSE_THRESHOLD,
        // Fuse defaults to scoring a match by how close it sits to the start of the field. A
        // keyword list is one joined string, so without this an exact keyword late in the list
        // (such as "max" on "Internal AI training") scores below the threshold and never matches.
        ignoreLocation: true,
        includeScore: true,
    })
    return Object.assign(fuse, { entries })
}

interface WordMatch {
    entry: SearchIndexEntry
    matchedWords: number
    score: number
}

const entryKey = (entry: SearchIndexEntry): string => `${entry.sectionId}::${entry.settingId}`

function matchWords(index: GlobalSearchFuse, words: string[]): WordMatch[] {
    const matches = new Map<string, WordMatch>()

    for (const word of words) {
        for (const { item, score } of index.search(word)) {
            const key = entryKey(item)
            const match = matches.get(key)
            if (match) {
                match.matchedWords += 1
                // Rank a multi-word query by its weakest word, so an entry that matches every
                // word closely stays ahead of one that only matches a single word well.
                match.score = Math.max(match.score, score ?? 1)
            } else {
                matches.set(key, { entry: item, matchedWords: 1, score: score ?? 1 })
            }
        }
    }

    return Array.from(matches.values())
}

/**
 * Fuse looks for the query letters in sequence inside one field, so an acronym such as "PAK"
 * never matches "Personal API keys". An uppercase query is an acronym on purpose, so its matches go first.
 * A lowercase one can be a real word ("rec" is also the start of "recordings"), so its matches
 * go after the fuzzy results.
 */
function addAcronymMatches(index: GlobalSearchFuse, term: string, results: SearchIndexEntry[]): SearchIndexEntry[] {
    if (term.length < MIN_ACRONYM_LENGTH || !/^[\p{L}\p{N}]+$/u.test(term)) {
        return results
    }

    const initials = term.toLowerCase()
    const acronymMatches = index.entries.filter((entry) => entry.titleInitials === initials)
    if (acronymMatches.length === 0) {
        return results
    }

    const resultKeys = new Set(results.map(entryKey))
    const newMatches = acronymMatches.filter((entry) => !resultKeys.has(entryKey(entry)))
    if (term !== term.toUpperCase()) {
        return [...results, ...newMatches].slice(0, RESULT_LIMIT)
    }

    const acronymKeys = new Set(acronymMatches.map(entryKey))
    const otherResults = results.filter((entry) => !acronymKeys.has(entryKey(entry)))
    return [...acronymMatches, ...otherResults].slice(0, RESULT_LIMIT)
}

/**
 * Fuse treats a query as one fuzzy pattern, so a multi-word query only matches when those
 * words sit together in one indexed field. That makes "session replay retention" and
 * "enable AI" return nothing. Searching word by word restores them: prefer the entries that
 * match every word, and fall back to the entries that match any word when none match all,
 * which is what rescues a query with a verb the index does not carry.
 */
export function searchSettingsIndex(index: GlobalSearchFuse, term: string): SearchIndexEntry[] {
    // Trim before searching: leading/trailing whitespace changes the pattern length and
    // inflates Fuse's effective edit budget (threshold × length), so an untrimmed term either
    // matches nothing or matches far too much.
    const trimmed = term.trim()
    if (!trimmed) {
        return []
    }

    const words = trimmed.split(/\s+/)
    if (words.length === 1) {
        const results = index.search(trimmed, { limit: RESULT_LIMIT }).map((result) => result.item)
        return addAcronymMatches(index, trimmed, results)
    }

    const matches = matchWords(index, words)
    const matchingEveryWord = matches.filter((match) => match.matchedWords === words.length)
    const ranked = matchingEveryWord.length > 0 ? matchingEveryWord : matches

    ranked.sort((a, b) => b.matchedWords - a.matchedWords || a.score - b.score)

    return ranked.slice(0, RESULT_LIMIT).map((match) => match.entry)
}
