import { ReactNode } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function NotificationCard({
    lemonClassName,
    children,
}: {
    lemonClassName: string
    children: ReactNode
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return <div className={todayRailNav ? 'flex flex-col gap-3' : lemonClassName}>{children}</div>
}
