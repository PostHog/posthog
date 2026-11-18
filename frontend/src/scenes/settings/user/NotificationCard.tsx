import { ReactNode } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillNotificationCard } from './QuillNotificationCard'

export function NotificationCard({
    lemonClassName,
    children,
}: {
    lemonClassName: string
    children: ReactNode
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillNotificationCard>{children}</QuillNotificationCard>
    }

    return <div className={lemonClassName}>{children}</div>
}
