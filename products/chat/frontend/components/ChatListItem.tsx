import { IconCornerDownRight } from '@posthog/icons'

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
            className={`py-2 px-3 cursor-pointer ${isActive ? 'bg-blue-100 font-semibold' : 'hover:bg-gray-200'}`}
            onClick={onClick}
        >
            <div className="font-bold text-sm mb-0.5">{user}</div>
            <div className="text-xs text-gray-500 mb-1">{date}</div>
            <div className="text-sm flex items-center gap-1">
                {isUnread && <span className="w-2 h-2 bg-red-500 rounded-full inline-block mr-1" />}
                {isReply && <IconCornerDownRight className="w-4 h-4 text-gray-400 rotate-180" />}
                <span>{message}</span>
            </div>
        </div>
    )
}
