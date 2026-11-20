import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { Button, Item, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { browserNotificationLogic } from '../../browserNotificationLogic'
import { QuillSettingsSwitchRow } from '../../components/QuillSettingsSwitchRow/QuillSettingsSwitchRow'

export function BrowserNotificationsSection(): JSX.Element | null {
    const { isSupported, permission, enabled, isPermissionDenied } = useValues(browserNotificationLogic)
    const { requestPermission, setEnabled } = useActions(browserNotificationLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    // Don't show if browser doesn't support notifications
    if (!isSupported) {
        return null
    }

    if (todayRailNav) {
        const label = 'Browser notifications'
        const description = 'Get notified in your browser when new support messages arrive.'

        return (
            <div className="flex flex-col gap-3">
                {isPermissionDenied || permission === 'default' ? (
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-col gap-0.5">
                            <Text size="xs" weight="medium" render={<span />}>
                                {label}
                            </Text>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {description}
                            </Text>
                        </div>
                        {isPermissionDenied ? (
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        Browser notifications are blocked. To enable them, click the lock icon in your
                                        browser's address bar and allow notifications for this site.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        ) : (
                            <div>
                                <Button variant="outline" onClick={requestPermission}>
                                    Enable browser notifications
                                </Button>
                            </div>
                        )}
                    </div>
                ) : (
                    <QuillSettingsSwitchRow
                        label={label}
                        description={description}
                        checked={enabled}
                        onCheckedChange={setEnabled}
                    />
                )}
                {enabled && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Not seeing notifications? Make sure notifications are enabled for your browser in your
                                operating system settings (e.g., macOS System Settings → Notifications → Chrome).
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
            </div>
        )
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
