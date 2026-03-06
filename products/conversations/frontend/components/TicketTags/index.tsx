import { useValues } from 'kea'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { tagsModel } from '~/models/tagsModel'

export interface TicketTagsProps {
    tags: string[]
    onChange: (tags: string[]) => void
    saving?: boolean
    className?: string
}

export function TicketTags({
    tags,
    onChange,
    saving = false,
    className = 'justify-end p-2',
}: TicketTagsProps): JSX.Element {
    const { tags: tagsAvailable, tagsLoading } = useValues(tagsModel)

    return (
        <ObjectTags
            tags={tags}
            onChange={onChange}
            saving={saving || tagsLoading}
            tagsAvailable={tagsAvailable}
            className={className}
            data-attr="ticket-tags"
            actionButtonSize="medium"
        />
    )
}
