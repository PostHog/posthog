import { ProfilePicture } from '@posthog/lemon-ui'

export interface MentionsPopoverProps {
    isOpen: boolean
    position: { top: number; left: number }
    members: any[]
    selectedIndex: number
    onSelect: (member: any) => void
}

export function MentionsPopover({
    isOpen,
    position,
    members,
    selectedIndex,
    onSelect,
}: MentionsPopoverProps): JSX.Element | null {
    if (!isOpen) {
        return null
    }

    return (
        <div
            style={{
                position: 'absolute',
                top: position.top + 20,
                left: position.left,
                zIndex: 1000,
                backgroundColor: 'white',
                border: '1px solid #d1d5db',
                borderRadius: '6px',
                boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
                maxHeight: '200px',
                overflowY: 'auto',
                minWidth: '200px',
            }}
        >
            {members.length > 0 ? (
                members.map((member, index) => (
                    <div
                        key={member.user.uuid}
                        className={`flex items-center gap-2 px-3 py-2 cursor-pointer ${
                            index === selectedIndex ? 'bg-blue-50' : 'hover:bg-gray-50'
                        }`}
                        onClick={() => onSelect(member)}
                    >
                        <ProfilePicture user={member.user} size="sm" />
                        <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-gray-900 truncate">
                                {member.user.first_name} &lt;{member.user.email}&gt;
                            </div>
                        </div>
                    </div>
                ))
            ) : (
                <div className="px-3 py-2 text-sm text-gray-500">No members found</div>
            )}
        </div>
    )
}
