import { AccessControlLevel } from '~/types'

export const ACCESS_LEVEL_ORDER: Record<AccessControlLevel, number> = {
    [AccessControlLevel.None]: 0,
    [AccessControlLevel.Viewer]: 1,
    [AccessControlLevel.Member]: 2,
    [AccessControlLevel.Editor]: 3,
    [AccessControlLevel.Manager]: 4,
    [AccessControlLevel.Admin]: 5,
}
