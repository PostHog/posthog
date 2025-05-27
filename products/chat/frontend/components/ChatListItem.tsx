import { IconCornerDownRight } from '@posthog/icons'
import { TZLabel } from 'lib/components/TZLabel'
import IconZendesk from 'public/services/zendesk.png'
import { PersonPropType } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
export function ChatListItem({
    person,
    message,
    subject = '',
    source_url = '',
    isActive,
    onClick,
    date,
    isUnread,
    isReply,
}: {
    person: PersonPropType | undefined
    message: string
    subject: string
    source_url: string
    isActive: boolean
    onClick: () => void
    date: string
    isUnread: boolean
    isReply: boolean
}): JSX.Element {
    return (
        <div
            className={`py-2 px-3 cursor-pointer ${isActive ? 'border-l-2 border-l-red-500' : 'hover:bg-gray-200'}`}
            onClick={onClick}
        >
            <div className="flex items-center justify-between gap-2">
                <div className="font-medium text-sm mb-1">
                    <PersonDisplay person={person} withIcon />
                </div>
                <TZLabel
                    className="overflow-hidden text-ellipsis text-xs text-secondary shrink-0"
                    time={date}
                    placement="right"
                />
            </div>
            <div className="text-sm flex items-center gap-1">
                {isUnread && <span className="w-2 h-2 bg-red-500 rounded-full inline-block mr-1" />}
                {isReply && <IconCornerDownRight className="w-4 h-4 text-gray-400 rotate-180" />}
                {source_url && source_url === 'zendesk' && <img src={IconZendesk} className="w-4 h-4" />}
                <span className="truncate">{subject ? `${subject} - ${message}` : message}</span>
            </div>
        </div>
    )
}
