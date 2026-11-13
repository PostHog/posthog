import { FilterMenuOpenTiming, FilterSearchSubMenu } from '@posthog/quill'

import { useTagPages } from 'lib/components/useTagPages'

export function QuillTagsFilterSubMenu({
    logicKey,
    selected,
    onChange,
    onOpened,
    dataAttr,
    optionDataAttr,
}: {
    logicKey: string
    selected: string[]
    onChange: (tags: string[]) => void
    onOpened?: (timing: FilterMenuOpenTiming) => void
    dataAttr: string
    optionDataAttr: string
}): JSX.Element {
    const tagPages = useTagPages(logicKey)
    return (
        <FilterSearchSubMenu
            label="Tags"
            allLabel="Any tag"
            pluralNoun="tags"
            options={tagPages.tags.map(({ tag }) => ({ value: tag, label: tag }))}
            selected={selected}
            onChange={onChange}
            loading={tagPages.awaitingFirstPage || tagPages.pageLoading}
            searchPlaceholder="Search tags"
            emptyText="No matching tags"
            onOpen={() => tagPages.setOpen(true)}
            onClose={() => tagPages.setOpen(false)}
            onSearchChange={tagPages.setSearch}
            onScrollEnd={tagPages.loadMore}
            error={tagPages.error ? "Couldn't load tags." : undefined}
            onRetry={tagPages.retry}
            onOpened={onOpened}
            dataAttr={dataAttr}
            optionDataAttr={optionDataAttr}
        />
    )
}
