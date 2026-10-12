import { useActions, useValues } from 'kea'

import { LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { LOCKED_BY_ORGANIZATION, lockedValueFor } from '../shared/notificationLocks'

const SETTING = 'task_comments_slack_dm'

export function TaskCommentSlackNotifications(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    const enforced = lockedValueFor(user?.notification_locks, SETTING)
    const stored = user?.notification_settings?.[SETTING]
    const checked = typeof enforced === 'boolean' ? enforced : stored !== false

    return (
        <div className="flex flex-col gap-2 max-w-200">
            <LemonSwitch
                bordered
                data-attr="task-comments-slack-dm"
                label={
                    <span className="flex items-center gap-2">
                        Slack DMs for task comments
                        {enforced !== null ? <LemonTag type="highlight">Set by your admin</LemonTag> : null}
                    </span>
                }
                checked={checked}
                onChange={(next) => {
                    if (user?.notification_settings) {
                        updateUser({ notification_settings: { ...user.notification_settings, [SETTING]: next } })
                    }
                }}
                disabledReason={enforced !== null ? LOCKED_BY_ORGANIZATION : userLoading ? 'Loading...' : undefined}
            />
            <p className="text-secondary text-xs mb-0">
                We find your Slack account by your email. If your Slack email is different, link your account in{' '}
                <Link to={urls.settings('user-personal-integrations')}>Personal integrations</Link>.
            </p>
        </div>
    )
}
