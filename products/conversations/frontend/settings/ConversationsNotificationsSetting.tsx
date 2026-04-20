import { useActions, useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { teamLogic } from 'scenes/teamLogic'

import { BrowserNotificationsSection } from './BrowserNotificationsSection'
import { supportSettingsLogic } from './supportSettingsLogic'

export function ConversationsNotificationsSetting(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { notificationRecipients } = useValues(supportSettingsLogic)
    const { setNotificationRecipients } = useActions(supportSettingsLogic)

    if (!currentTeam?.conversations_enabled) {
        return <p className="text-muted text-sm">Enable conversations API first.</p>
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-4 justify-between">
                <div>
                    <label className="font-medium">Email notification recipients</label>
                    <p className="text-xs text-muted-alt">
                        Team members who will receive email notifications when new tickets are created.
                    </p>
                </div>
                <MemberSelectMultiple idKey="id" value={notificationRecipients} onChange={setNotificationRecipients} />
            </div>
            <LemonDivider />
            <BrowserNotificationsSection />
        </div>
    )
}
