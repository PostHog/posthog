import { useMountedLogic } from 'kea'

import { noEventsBannerLogic } from '~/layout/navigation/noEventsBannerLogic'

export function TodayFirstEventWatcher(): null {
    useMountedLogic(noEventsBannerLogic)
    return null
}
