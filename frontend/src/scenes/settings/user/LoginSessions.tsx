import { useActions, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconLaptop, IconLeave } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { UserAuthSessionApi } from '~/generated/core/api.schemas'

import { loginSessionsLogic } from './loginSessionsLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function LoginSessions(): JSX.Element {
    const { loginSessions, loginSessionsLoading } = useValues(loginSessionsLogic)
    const { revokeSession, revokeOtherSessions } = useActions(loginSessionsLogic)

    const hasOtherSessions = loginSessions.some((session) => !session.is_current)

    const handleRevoke = (session: UserAuthSessionApi): void => {
        LemonDialog.open({
            title: 'Log out of this device?',
            description: 'This device will be signed out of your PostHog account immediately.',
            primaryButton: {
                children: 'Log out',
                status: 'danger',
                onClick: () => revokeSession(session.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const handleRevokeOthers = (): void => {
        LemonDialog.open({
            title: 'Log out everywhere else?',
            description: 'Every device except this one will be signed out of your PostHog account immediately.',
            primaryButton: {
                children: 'Log out everywhere else',
                status: 'danger',
                onClick: () => revokeOtherSessions(),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    loading={loginSessionsLoading}
                    disabledReason={hasOtherSessions ? undefined : 'No other devices to log out'}
                    onClick={handleRevokeOthers}
                >
                    Log out everywhere else
                </LemonButton>
            </div>
            <LemonTable
                dataSource={loginSessions}
                loading={loginSessionsLoading}
                columns={[
                    {
                        title: 'Device',
                        dataIndex: 'device',
                        render: (_, session) => (
                            <div className="flex items-center gap-2">
                                <span className="font-medium">{session.device || 'Unknown device'}</span>
                                {session.is_current && (
                                    <LemonTag type="success" size="small">
                                        This device
                                    </LemonTag>
                                )}
                            </div>
                        ),
                    },
                    {
                        title: 'Location',
                        dataIndex: 'location',
                        render: (_, session) => session.location || <span className="text-muted">Unknown</span>,
                    },
                    {
                        title: 'Signed in with',
                        dataIndex: 'login_method',
                        render: (_, session) => session.login_method || <span className="text-muted">—</span>,
                    },
                    {
                        title: 'Started at',
                        dataIndex: 'created_at',
                        render: (_, session) =>
                            session.created_at ? (
                                humanFriendlyDetailedTime(session.created_at, 'MMMM DD, YYYY', 'h:mm A')
                            ) : (
                                <span className="text-muted">Unknown</span>
                            ),
                    },
                    {
                        title: 'Last active',
                        dataIndex: 'last_activity',
                        // Minute precision: last_activity is throttled to ~5-min updates, so seconds would be false precision.
                        render: (_, session) =>
                            humanFriendlyDetailedTime(session.last_activity, 'MMMM DD, YYYY', 'h:mm A'),
                    },
                    {
                        title: '',
                        width: 0,
                        render: (_, session) =>
                            session.is_current ? null : (
                                <LemonButton
                                    icon={<IconLeave />}
                                    status="danger"
                                    size="small"
                                    tooltip="Log out of this device"
                                    disabledReason={loginSessionsLoading ? 'Working…' : undefined}
                                    onClick={() => handleRevoke(session)}
                                />
                            ),
                    },
                ]}
                emptyState={
                    <div className="flex items-center gap-4 py-4">
                        <HedgehogMagnifyingGlass className="w-16 h-16" />
                        <div>
                            <div className="flex items-center gap-2 font-semibold">
                                <IconLaptop className="text-xl text-secondary" />
                                No active logins found
                            </div>
                            <p className="text-secondary mt-1 mb-0">
                                Devices signed in to your account will appear here.
                            </p>
                        </div>
                    </div>
                }
            />
        </div>
    )
}
