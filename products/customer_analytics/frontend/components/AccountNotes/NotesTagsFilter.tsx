import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TagSelect } from 'lib/components/TagSelect'

import { loadAccountNoteTags } from './loadAccountNoteTags'

interface NotesTagsFilterProps {
    value: string[]
    onChange: (tags: string[]) => void
    'data-attr'?: string
}

// Same control as the Accounts tab's tag filter, but it offers only the tags already on account notes.
export function NotesTagsFilter({ value, onChange, 'data-attr': dataAttr }: NotesTagsFilterProps): JSX.Element {
    const buttonLabel = value.length === 0 ? 'All tags' : value.length === 1 ? value[0] : `${value.length} tags`

    return (
        <div className="flex gap-1 items-center" data-attr={dataAttr}>
            <TagSelect value={value} onChange={onChange} loadTags={loadAccountNoteTags}>
                {() => (
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {buttonLabel}
                    </LemonButton>
                )}
            </TagSelect>
            {value.length > 0 && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconX />}
                    onClick={() => onChange([])}
                    tooltip="Clear tag filter"
                />
            )}
        </div>
    )
}
