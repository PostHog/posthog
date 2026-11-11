import { useId } from 'react'

import { LemonInputSelect, LemonInputSelectProps } from '@posthog/lemon-ui'

import { LoadTags } from './tagSelectLogic'
import { useTagPages } from './useTagPages'

type TagsInputSelectProps = Pick<
    LemonInputSelectProps,
    | 'onBlur'
    | 'placeholder'
    | 'autoFocus'
    | 'fullWidth'
    | 'size'
    | 'className'
    | 'popoverClassName'
    | 'data-attr'
    | 'id'
    | 'disabled'
> & {
    value: string[]
    onChange: (tags: string[]) => void
    saving?: boolean
    loadTags?: LoadTags
}

/** A tag editor that suggests the project's tags a page at a time, so it stays fast on projects with many tags. */
export function TagsInputSelect({
    value,
    onChange,
    saving,
    loadTags,
    ...inputProps
}: TagsInputSelectProps): JSX.Element {
    const { tags, awaitingFirstPage, pageLoading, error, setOpen, setSearch, retry } = useTagPages(useId(), loadTags)

    return (
        <LemonInputSelect
            mode="multiple"
            allowCustomValues
            value={value}
            options={tags.map(({ tag }) => ({ key: tag, label: tag }))}
            onChange={onChange}
            onFocus={() => setOpen(true)}
            onInputChange={setSearch}
            disableFiltering
            loading={saving || awaitingFirstPage || pageLoading}
            // An action shows even when selected tags fill the list, where an empty state would stay hidden.
            action={error ? { children: "Couldn't load tags. Try again", onClick: retry } : undefined}
            {...inputProps}
        />
    )
}
