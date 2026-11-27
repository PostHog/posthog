import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { userLogic } from 'scenes/userLogic'

export function AllowImpersonation(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => updateUser({ allow_impersonation: checked })

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    PostHog support staff may need to log in as you to help debug issues. If you disable this setting,
                    support staff will not be able to access your account directly. Read our{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://posthog.com/handbook/company/security#impersonating-users"
                                target="_blank"
                            />
                        }
                    >
                        policy on user impersonation
                    </Button>
                    .
                </Text>
                <QuillSettingSwitch
                    label="Allow support to log in as me"
                    dataAttr="allow-impersonation"
                    checked={user?.allow_impersonation ?? true}
                    onCheckedChange={handleChange}
                    disabled={userLoading}
                />
            </div>
        )
    }

    return (
        <div>
            <p>
                PostHog support staff may need to log in as you to help debug issues. If you disable this setting,
                support staff will not be able to access your account directly. Read our{' '}
                <Link to="https://posthog.com/handbook/company/security#impersonating-users" target="_blank">
                    policy on user impersonation
                </Link>
                .
            </p>
            <LemonSwitch
                label="Allow support to log in as me"
                data-attr="allow-impersonation"
                onChange={handleChange}
                checked={user?.allow_impersonation ?? true}
                disabled={userLoading}
                bordered
            />
        </div>
    )
}
