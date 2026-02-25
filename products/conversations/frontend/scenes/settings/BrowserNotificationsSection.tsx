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
        <>
            <div className="flex items-center gap-4 justify-between">
                <div>
                    <label className="w-40 shrink-0 font-medium">Browser notifications</label>
                    <p className="text-xs text-muted-alt mb-2">
                        Get notified in your browser when new support messages arrive.
                    </p>
                </div>
                {isPermissionDenied ? (
                    <LemonBanner type="info">
                        Browser notifications are blocked. To enable them, click the lock icon in your browser's address
                        bar and allow notifications for this site.
                    </LemonBanner>
                ) : permission === 'default' ? (
                    <LemonButton type="secondary" onClick={requestPermission}>
                        Enable browser notifications
                    </LemonButton>
                ) : (
                    <LemonSwitch checked={enabled} onChange={setEnabled} />
                )}
            </div>
            {enabled && (
                <LemonBanner type="info" className="mb-2">
                    Not seeing notifications? Make sure notifications are enabled for your browser in your operating
                    system settings (e.g., macOS System Settings → Notifications → Chrome).
                </LemonBanner>
            )}
        </>
    )
}
