import { combineUrl } from 'kea-router'

import { IconArrowRight } from '@posthog/icons'

import { SearchItem } from 'lib/components/Search/searchItems'
import { urls } from 'scenes/urls'

import { fileSystemTypes } from '~/products'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { FileSystemListQuery, OrganizationMemberType, UserType } from '~/types'

import { FilterOptions, QueryChip, ResolvedQuery, ValueOption, queryAsText, tokenize, unquote } from './commandKQuery'
import type { ViewAll } from './commandKSections'

/** Short words people type for a type, on top of its name and key. */
const TYPE_ALIASES: Record<string, string[]> = {
    feature_flag: ['flag', 'flags'],
    session_recording_playlist: ['playlist', 'replay', 'recording'],
    early_access_feature: ['eaf', 'beta'],
    workflows: ['workflow'],
    notebook: ['doc'],
}

interface FileSystemTypeDefinition {
    name?: string
    iconType?: string
    listHref?: (query?: FileSystemListQuery) => string
}

const FILE_SYSTEM_TYPES = fileSystemTypes as Record<string, FileSystemTypeDefinition>

const typeDefinition = (type: string): FileSystemTypeDefinition | undefined =>
    Object.hasOwn(FILE_SYSTEM_TYPES, type) ? FILE_SYSTEM_TYPES[type] : undefined

// Some manifest names are already plural, such as "Tasks".
export const pluralTypeName = (label: string): string => {
    const name = label.toLowerCase()
    return name.endsWith('s') ? name : `${name}s`
}

let cachedTypeOptions: ValueOption[] | null = null

/** Every file system type from the product manifests, alphabetized. The manifests never change at runtime. */
const typeOptions = (): ValueOption[] => {
    if (cachedTypeOptions === null) {
        cachedTypeOptions = Object.entries(FILE_SYSTEM_TYPES)
            .flatMap(([type, definition]) =>
                definition.name
                    ? [
                          {
                              value: type,
                              label: definition.name,
                              aliases: [
                                  type,
                                  definition.name.toLowerCase().replace(/\s+/g, '-'),
                                  ...(TYPE_ALIASES[type] ?? []),
                              ],
                              iconType: definition.iconType ?? type,
                          },
                      ]
                    : []
            )
            .sort((a, b) => a.label.localeCompare(b.label))
    }
    return cachedTypeOptions
}

const memberOption = (member: OrganizationMemberType): ValueOption => {
    const { first_name, last_name, email } = member.user
    return {
        value: email,
        label: [first_name, last_name].filter(Boolean).join(' ') || email,
        aliases: [first_name, last_name, email].filter((alias): alias is string => !!alias),
    }
}

/** `me` first, then everyone else in the organization. */
const userOptions = (members: OrganizationMemberType[], user: UserType | null): ValueOption[] => [
    { value: 'me', label: 'Me', aliases: user ? [user.first_name, user.email].filter(Boolean) : [] },
    ...members.filter((member) => member.user.uuid !== user?.uuid).map(memberOption),
]

export function buildFilterOptions(
    members: OrganizationMemberType[],
    user: UserType | null,
    folders: FileSystemEntry[] | null
): FilterOptions {
    return {
        is: typeOptions(),
        createdBy: userOptions(members, user),
        in: (folders ?? []).map((folder) => ({ value: folder.path, label: folder.path })),
        name: [],
    }
}

/** List pages for types whose manifest registers no `listHref`. */
const LIST_HREF_FALLBACKS: Record<string, (query: FileSystemListQuery) => string> = {
    dashboard: ({ searchText }) => combineUrl(urls.dashboards(), { search: searchText }).url,
    notebook: () => urls.notebooks(),
}

const isExcluded = (raw: string): boolean => raw.startsWith('-') || raw.startsWith('!')

const includedWords = (freeText: string): string[] =>
    tokenize(freeText)
        .map((token) => unquote(token.raw))
        .filter((word) => word && !isExcluded(word))

const includedNames = (filters: QueryChip[]): string[] =>
    filters.filter((filter) => filter.key === 'name' && !filter.negated).map((filter) => filter.value)

const listQueryFor = (typeChip: QueryChip, { filters, freeText }: ResolvedQuery): FileSystemListQuery => ({
    searchText: [...includedNames(filters), ...includedWords(freeText)].join(' ') || undefined,
    queryWithoutType:
        queryAsText(
            freeText,
            filters.filter((filter) => filter !== typeChip)
        ) || undefined,
})

// With only filters the list page is the likely target; once there is search text, the matches matter more.
export function viewAllFor(resolved: ResolvedQuery): ViewAll | null {
    const chip = resolved.filters.find((candidate) => candidate.key === 'is' && !candidate.negated)
    if (!chip) {
        return null
    }
    const listHref = typeDefinition(chip.value)?.listHref ?? LIST_HREF_FALLBACKS[chip.value]
    if (!listHref) {
        return null
    }
    const href = listHref(listQueryFor(chip, resolved))
    const name = `View all ${pluralTypeName(chip.label)}`
    const item: SearchItem = {
        id: `view-all-${chip.value}`,
        name,
        displayName: name,
        category: 'results',
        href,
        icon: <IconArrowRight className="size-4 shrink-0 text-muted-foreground" />,
        record: { type: chip.value },
    }
    return { item, placement: resolved.freeText.trim() ? 'trail' : 'lead' }
}
