import { useId, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectProps } from '@posthog/lemon-ui'

import { TagOptionLabel } from './TagOptionLabel'
import { LoadTags, TagObjectType } from './tagSelectLogic'
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
    objectType?: TagObjectType
}

/** A tag editor that suggests the project's tags a page at a time, so it stays fast on projects with many tags. */
export function TagsInputSelect({
    value,
    onChange,
    saving,
    loadTags,
    objectType,
    ...inputProps
}: TagsInputSelectProps): JSX.Element {
    const { tags, awaitingFirstPage, pageLoading, error, setOpen, setSearch, retry } = useTagPages(
        useId(),
        loadTags,
        objectType
    )

    const options = useMemo(
        () =>
            tags
                .filter(({ tag }) => !value.includes(tag))
                .map((option) => ({
                    key: option.tag,
                    label: option.tag,
                    labelComponent: option.count !== undefined ? <TagOptionLabel {...option} /> : undefined,
                })),
        [tags, value]
    )

    return (
        <LemonInputSelect
            mode="multiple"
            allowCustomValues
            hideSelectedOptions
            value={value}
            options={options}
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
