import { Tooltip } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

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
    const tagsDisplay = (
        <ObjectTags
            tags={tags}
            {...(disabledReason
                ? { staticOnly: true as const }
                : {
                      onChange,
                      saving,
                  })}
            className={className}
            data-attr="ticket-tags"
            actionButtonSize="medium"
            wrap
        />
    )

    return disabledReason ? (
        <Tooltip title={disabledReason}>
            <span className="min-w-0">{tagsDisplay}</span>
        </Tooltip>
    ) : (
        tagsDisplay
    )
}
