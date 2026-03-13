import { useValues } from 'kea'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { tagsModel } from '~/models/tagsModel'

export interface TicketTagsProps {
    tags: string[]
    onChange: (tags: string[]) => void
    saving?: boolean
}

export function TicketTags({ tags, onChange, saving = false }: TicketTagsProps): JSX.Element {
    const { tags: tagsAvailable, tagsLoading } = useValues(tagsModel)

    return (
        <ObjectTags
            tags={tags}
            onChange={onChange}
            saving={saving || tagsLoading}
            tagsAvailable={tagsAvailable}
            className="justify-end p-2"
            data-attr="ticket-tags"
        />
    )
}
