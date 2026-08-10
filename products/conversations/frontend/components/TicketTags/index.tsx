import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { tagsModel } from '~/models/tagsModel'

export interface TicketTagsProps {
    tags: string[]
    onChange: (tags: string[]) => void
    saving?: boolean
    className?: string
    disabledReason?: string
}

export function TicketTags({
    tags,
    onChange,
    saving = false,
    className = 'justify-end p-2',
    disabledReason,
}: TicketTagsProps): JSX.Element {
    const { tags: tagsAvailable, tagsLoading } = useValues(tagsModel)

    const tagsDisplay = (
        <ObjectTags
            tags={tags}
            {...(disabledReason
                ? { staticOnly: true as const }
                : {
                      onChange,
                      saving: saving || tagsLoading,
                      tagsAvailable,
                  })}
            className={className}
            data-attr="ticket-tags"
            actionButtonSize="medium"
        />
    )

    return disabledReason ? (
        <Tooltip title={disabledReason}>
            <span>{tagsDisplay}</span>
        </Tooltip>
    ) : (
        tagsDisplay
    )
}
