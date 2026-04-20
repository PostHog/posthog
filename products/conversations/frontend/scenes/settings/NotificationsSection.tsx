import { useActions, useValues } from 'kea'

import { LemonCard, LemonDivider } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { BrowserNotificationsSection } from './BrowserNotificationsSection'
import { supportSettingsLogic } from './supportSettingsLogic'

export function NotificationsSection(): JSX.Element {
    const { setNotificationRecipients } = useActions(supportSettingsLogic)
    const { notificationRecipients } = useValues(supportSettingsLogic)

    return (
        <SceneSection
            title="Notifications"
            description="We recommend using workflows to set custom notifications, e.g. when a new ticket is created or a new message is received."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label className="w-40 shrink-0 font-medium">Email notifications</label>
                        <p className="text-xs text-muted-alt">
                            Team members who will receive email notifications when new tickets are created.
                        </p>
                    </div>
                    <MemberSelectMultiple
                        idKey="id"
                        value={notificationRecipients}
                        onChange={setNotificationRecipients}
                    />
                </div>
                <LemonDivider />
                <BrowserNotificationsSection />
            </LemonCard>
        </SceneSection>
    )
}
