import { useActions, useValues } from 'kea'

import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInputSelect } from '@posthog/lemon-ui'

import { tagsModel } from '~/models/tagsModel'

interface NotesTagsFilterProps {
    value: string[]
    onChange: (tags: string[]) => void
    'data-attr'?: string
}

// Same control as the Accounts tab's tag filter: a dropdown multi-select over the team's tags.
export function NotesTagsFilter({ value, onChange, 'data-attr': dataAttr }: NotesTagsFilterProps): JSX.Element {
    const { tags: tagsAvailable, tagsLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)

    const buttonLabel = value.length === 0 ? 'All tags' : value.length === 1 ? value[0] : `${value.length} tags`

    return (
        <div className="flex gap-1 items-center" data-attr={dataAttr}>
            <LemonDropdown
                closeOnClickInside={false}
                onVisibilityChange={(open) => open && loadTagsIfNeeded()}
                overlay={
                    <div className="p-2 min-w-64">
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            value={value}
                            options={(tagsAvailable || []).map((tag: string) => ({ key: tag, label: tag }))}
                            loading={tagsLoading}
                            onChange={onChange}
                            placeholder="Select or type tags..."
                        />
                    </div>
                }
            >
                <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                    {buttonLabel}
                </LemonButton>
            </LemonDropdown>
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
