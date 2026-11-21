import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TagSelect } from 'lib/components/TagSelect'

interface TagsFilterProps {
    value: string[]
    onChange: (tags: string[]) => void
    'data-attr'?: string
}

// Same control as the Accounts tab's tag filter: a dropdown multi-select over the team's tags.
export function TagsFilter({ value, onChange, 'data-attr': dataAttr }: TagsFilterProps): JSX.Element {
    const buttonLabel = value.length === 0 ? 'All tags' : value.length === 1 ? value[0] : `${value.length} tags`

    return (
        <div className="flex gap-1 items-center" data-attr={dataAttr}>
            <TagSelect value={value} onChange={onChange}>
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
