import { useActions, useValues } from 'kea'

import { LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'
import { Badge, Button, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (next: boolean): void => {
        if (user?.notification_settings) {
            updateUser({ notification_settings: { ...user.notification_settings, [SETTING]: next } })
        }
    }

    const disabledReason = enforced !== null ? LOCKED_BY_ORGANIZATION : userLoading ? 'Loading...' : undefined

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2 max-w-200">
                <QuillSettingSwitch
                    dataAttr="task-comments-slack-dm"
                    label={
                        <span className="flex flex-wrap items-center gap-2">
                            Slack DMs for task comments
                            {enforced !== null ? <Badge variant="info">Set by your admin</Badge> : null}
                        </span>
                    }
                    checked={checked}
                    onCheckedChange={handleChange}
                    disabledReason={disabledReason}
                />
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    We find your Slack account by your email. If your Slack email is different, link your account in{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.settings('user-personal-integrations')} />}
                    >
                        Personal integrations
                    </Button>
                    .
                </Text>
            </div>
        )
    }

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
                onChange={handleChange}
                disabledReason={disabledReason}
            />
            <p className="text-secondary text-xs mb-0">
                We find your Slack account by your email. If your Slack email is different, link your account in{' '}
                <Link to={urls.settings('user-personal-integrations')}>Personal integrations</Link>.
            </p>
        </div>
    )
}
