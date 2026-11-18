import { ReactNode } from 'react'

import { FilterSubMenu } from '@posthog/quill'

import { useTodaySheetMenu } from './todaySheetMenuContext'
import { TodaySheetSub } from './TodaySheetSub'

interface TodayRecentFilterSubmenuProps {
    label: string
    /** The choice in force, shown beside the label. */
    value: string
    /** The choice differs from the default, so the value takes the primary color, like PostHog Desktop. */
    narrowed?: boolean
    children: ReactNode
}

export function TodayRecentFilterSubmenu({
    label,
    value,
    narrowed = false,
    children,
}: TodayRecentFilterSubmenuProps): JSX.Element {
    const sheet = useTodaySheetMenu()
    if (sheet) {
        return (
            <TodaySheetSub label={label} title={label} value={value} narrowed={narrowed}>
                {children}
            </TodaySheetSub>
        )
    }
    return (
        <FilterSubMenu label={label} value={value} active={narrowed}>
            {children}
        </FilterSubMenu>
    )
}
