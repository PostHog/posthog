import { IconPlus } from '@posthog/icons'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'

import { ExtensionToolLoading } from './ExtensionToolLoading'

interface ExtensionEntityListProps {
    /** For example "action", used in the search, empty state and saved copy. */
    noun: string
    pluralNoun: string
    items: { id: number; name: string | null }[] | null
    loading: boolean
    searchTerm: string
    onSearch: (searchTerm: string) => void
    onSelect: (id: number) => void
    onCreate: () => void
    /** The item the page just saved, with its page in PostHog. */
    saved: { name: string | null; url: string } | null
    viewAllUrl: string
    emptyText: string
    /** Shown above the search, for example a warning about the page. */
    notice?: JSX.Element | false
    hint?: string
    dataAttrs: { search: string; row: string; create: string; openSaved: string }
}

/** The list that opens the actions and experiments tools: search, pick an item to edit it, or make a new one. */
export function ExtensionEntityList({
    noun,
    pluralNoun,
    items,
    loading,
    searchTerm,
    onSearch,
    onSelect,
    onCreate,
    saved,
    viewAllUrl,
    emptyText,
    notice,
    hint,
    dataAttrs,
}: ExtensionEntityListProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {notice}
            {saved && (
                <LemonBanner
                    type="success"
                    action={{
                        children: 'Open in PostHog',
                        to: saved.url,
                        targetBlank: true,
                        'data-attr': dataAttrs.openSaved,
                    }}
                >
                    Saved {saved.name ? `"${saved.name}"` : `the ${noun}`}.
                </LemonBanner>
            )}
            <LemonInput
                type="search"
                size="small"
                placeholder={`Search ${pluralNoun}`}
                value={searchTerm}
                onChange={onSearch}
                data-attr={dataAttrs.search}
            />
            {hint && <div className="text-xs text-secondary">{hint}</div>}
            {!items || (loading && items.length === 0) ? (
                <ExtensionToolLoading />
            ) : items.length === 0 ? (
                <div className="text-secondary text-xs p-2">
                    {searchTerm ? `No ${pluralNoun} match your search.` : emptyText}
                </div>
            ) : (
                <ol className="flex flex-col gap-px m-0 p-0 list-none">
                    {items.map((item, index) => (
                        <li key={item.id}>
                            <LemonButton
                                fullWidth
                                size="small"
                                onClick={() => onSelect(item.id)}
                                data-attr={dataAttrs.row}
                            >
                                <span className="inline-block min-w-6 text-secondary">{index + 1}.</span>
                                <span className="truncate">
                                    {item.name || <span className="italic text-secondary">Untitled</span>}
                                </span>
                            </LemonButton>
                        </li>
                    ))}
                </ol>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Link to={viewAllUrl} target="_blank" className="text-xs">
                    View all {pluralNoun} <IconOpenInNew />
                </Link>
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={onCreate}
                    data-attr={dataAttrs.create}
                >
                    New {noun}
                </LemonButton>
            </div>
        </div>
    )
}
