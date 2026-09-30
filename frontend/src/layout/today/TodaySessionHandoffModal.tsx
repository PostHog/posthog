import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { userLogic } from 'scenes/userLogic'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'

interface TodaySessionHandoffModalProps {
    sessionId: string
}

export function TodaySessionHandoffModal({ sessionId }: TodaySessionHandoffModalProps): JSX.Element {
    const { user } = useValues(userLogic)
    const { handoffUser, pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { closeHandoff, setHandoffUser, handOffSession } = useActions(todaySessionMenuLogic)
    const pending = pendingSessionIds.includes(sessionId)

    return (
        <LemonModal
            isOpen
            onClose={pending ? undefined : closeHandoff}
            title="Hand off this session"
            description="The person you choose takes over this session. They steer it and get its notifications. Only they can hand it back."
            width={480}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeHandoff}
                        disabledReason={pending ? 'Handing off this session' : undefined}
                        data-attr="today-session-handoff-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={pending}
                        disabledReason={handoffUser ? undefined : 'Choose who takes over'}
                        onClick={() => handoffUser && handOffSession(sessionId, handoffUser)}
                        data-attr="today-session-handoff-confirm"
                    >
                        Hand off
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <LemonLabel>Choose who takes over</LemonLabel>
                <MemberSelect
                    value={handoffUser?.id ?? null}
                    excludedMembers={user ? [user.id] : []}
                    allowNone={false}
                    defaultLabel="Choose a person"
                    onChange={setHandoffUser}
                    type="secondary"
                />
            </div>
        </LemonModal>
    )
}
