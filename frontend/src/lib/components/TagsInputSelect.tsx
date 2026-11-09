import { useId } from 'react'

import { LemonButton, LemonInputSelect, LemonInputSelectProps } from '@posthog/lemon-ui'

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
            emptyStateComponent={
                error ? (
                    <div className="flex items-center justify-between gap-2 px-2 py-1">
                        <span className="text-secondary">Couldn't load tags.</span>
                        <LemonButton size="xsmall" type="secondary" onClick={retry}>
                            Try again
                        </LemonButton>
                    </div>
                ) : undefined
            }
            {...inputProps}
        />
    )
}
