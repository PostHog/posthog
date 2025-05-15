import { IconCornerDownRight } from '@posthog/icons'
import { TZLabel } from 'lib/components/TZLabel'
export function ChatListItem({
    user,
    message,
    isActive,
    onClick,
    date,
    isUnread,
    isReply,
}: {
    user: string
    message: string
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
            <div className="font-medium text-sm mb-1">{user}</div>
            <TZLabel
                className="overflow-hidden text-ellipsis text-xs text-secondary shrink-0"
                time={date}
                placement="right"
            />
            <div className="text-sm flex items-center gap-1">
                {isUnread && <span className="w-2 h-2 bg-red-500 rounded-full inline-block mr-1" />}
                {isReply && <IconCornerDownRight className="w-4 h-4 text-gray-400 rotate-180" />}
                <span className="truncate">{message}</span>
            </div>
        </div>
    )
}
