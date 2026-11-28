import { Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

/** Tells a person without staff access how to get it, on the materialized columns page. */
export function MaterializedColumnsStaffNotice(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return todayRailNav ? (
        <div className="flex flex-col gap-2">
            <Text size="xs" render={<p className="m-0" />}>
                Only users with staff access can manage materialized columns. Please contact your instance admin.
            </Text>
            <Text size="xs" render={<p className="m-0" />}>
                If you're an admin and don't have access, set <code>is_staff=true</code> for your user on the PostgreSQL{' '}
                <code>posthog_user</code> table.
            </Text>
        </div>
    ) : (
        <>
            <p>Only users with staff access can manage materialized columns. Please contact your instance admin.</p>
            <p>
                If you're an admin and don't have access, set <code>is_staff=true</code> for your user on the PostgreSQL{' '}
                <code>posthog_user</code> table.
            </p>
        </>
    )
}
