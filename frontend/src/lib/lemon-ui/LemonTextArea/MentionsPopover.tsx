import { ProfilePicture } from '@posthog/lemon-ui'
import { cn } from 'lib/utils/css-classes'
import { FloatingPortal } from '@floating-ui/react'

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
        <FloatingPortal>
            <div
                className="fixed bg-bg-light border rounded shadow-md max-h-[200px] overflow-y-auto min-w-[200px]"
                style={{
                    top: `${position.top + 20}px`,
                    left: `${position.left}px`,
                    zIndex: 9999,
                }}
            >
                {members.length > 0 ? (
                    members.map((member, index) => {
                        return (
                            <div
                                key={member.user.uuid}
                                className={cn(
                                    'flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-fill-highlight-100',
                                    index === selectedIndex && 'bg-fill-highlight-100'
                                )}
                                onClick={() => onSelect(member)}
                            >
                                <ProfilePicture user={member.user} size="sm" />
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm font-medium text-3000 truncate">
                                        {member.user.first_name} &lt;{member.user.email}&gt;
                                    </div>
                                </div>
                            </div>
                        )
                    })
                ) : (
                    <div className="px-3 py-2 text-sm text-3000">No members found</div>
                )}
            </div>
        </FloatingPortal>
    )
}
