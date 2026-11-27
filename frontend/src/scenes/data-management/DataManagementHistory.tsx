import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { QuillActivityLog } from 'lib/components/ActivityLog/QuillActivityLog'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { ActivityScope } from '~/types'

const CAPTION =
    'Only actions taken in the UI are captured in History. Automatic creation of definitions by ingestion is not shown here.'

/** The data management History tab, which shows the quill activity log under `today-rail-nav`. */
export function DataManagementHistory(): JSX.Element | null {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return todayRailNav ? (
        <QuillActivityLog scope={ActivityScope.DATA_MANAGEMENT} caption={CAPTION} />
    ) : (
        <ActivityLog scope={ActivityScope.DATA_MANAGEMENT} caption={CAPTION} />
    )
}
