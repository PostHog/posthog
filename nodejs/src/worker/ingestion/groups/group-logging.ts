import { GroupTypeIndex, TeamId } from '../../../types'
import { groupUpdateVersionMismatchCounter } from '../../../utils/db/metrics'
import { logger } from '../../../utils/logger'

export function logVersionMismatch(
    teamId: TeamId,
    groupTypeIndex: GroupTypeIndex,
    groupKey: string,
    versionDisparity: number
): void {
    logger.warn('👥', 'Group update version mismatch', {
        team_id: teamId,
        group_type_index: groupTypeIndex,
        group_key: groupKey,
        version_disparity: versionDisparity,
    })
    groupUpdateVersionMismatchCounter.labels({ type: 'version_mismatch' }).inc()
}

export function logMissingRow(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): void {
    logger.warn('👥', 'Group update row missing', {
        team_id: teamId,
        group_type_index: groupTypeIndex,
        group_key: groupKey,
    })
    groupUpdateVersionMismatchCounter.labels({ type: 'row_missing' }).inc()
}
