import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { browserNotificationLogic } from '../../browserNotificationLogic'

export function BrowserNotificationsSection(): JSX.Element | null {
    const { isSupported, permission, enabled, isPermissionDenied } = useValues(browserNotificationLogic)
    const { requestPermission, setEnabled } = useActions(browserNotificationLogic)

    // Don't show if browser doesn't support notifications
    if (!isSupported) {
        return null
    }

    return (
        <div className="mb-8 max-w-[800px]">
            <h3>Browser notifications</h3>
            <p>Get notified in your browser when new support messages arrive.</p>

            {isPermissionDenied ? (
                <LemonBanner type="info">
                    Browser notifications are blocked. To enable them, click the lock icon in your browser's address bar
                    and allow notifications for this site.
                </LemonBanner>
            ) : permission === 'default' ? (
                <LemonButton type="secondary" onClick={requestPermission}>
                    Enable browser notifications
                </LemonButton>
            ) : (
                <>
                    <LemonSwitch
                        checked={enabled}
                        onChange={setEnabled}
                        label={enabled ? 'Browser notifications enabled' : 'Browser notifications disabled'}
                        bordered
                    />
                    {enabled && (
                        <LemonBanner type="info" className="mt-2">
                            Not seeing notifications? Make sure notifications are enabled for your browser in your
                            operating system settings (e.g., macOS System Settings → Notifications → Chrome).
                        </LemonBanner>
                    )}
                </>
            )}
        </div>
    )
}
