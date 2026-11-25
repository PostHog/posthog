import { useMountedLogic } from 'kea'

import { todaySpacesLogic } from './todaySpacesLogic'

export function TodaySpacesLogicMount(): null {
    useMountedLogic(todaySpacesLogic)
    return null
}
