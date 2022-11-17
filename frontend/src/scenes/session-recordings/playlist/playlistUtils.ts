import { PropertyOperator, RecordingFilters, SessionRecordingType } from '~/types'
import { cohortsModelType } from '~/models/cohortsModelType'
import { toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { convertPropertyGroupToProperties, genericOperatorMap, toParams } from 'lib/utils'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import api from 'lib/api'

function getOperatorSymbol(operator: PropertyOperator | null): string {
    if (!operator) {
        return '?'
    }
    if (genericOperatorMap?.[operator]) {
        return genericOperatorMap[operator].slice(0, 1)
    }
    return String(operator)
}

export function summarizePlaylistFilters(
    filters: Partial<RecordingFilters>,
    cohortsById: cohortsModelType['values']['cohortsById']
): string | null {
    let summary: string
    const localFilters = toLocalFilters(filters)

    summary = localFilters
        .map((localFilter) => {
            return getDisplayNameFromEntityFilter(localFilter)
        })
        .join(' & ')

    const properties = convertPropertyGroupToProperties(filters.properties)
    if (properties && (properties.length ?? 0) > 0) {
        const propertiesSummary = properties
            .map((property) => {
                if (property.type === 'person') {
                    return `${getKeyMapping(property.key, 'event')?.label || property.key} ${getOperatorSymbol(
                        property.operator
                    )} ${property.value}`
                }
                if (property.type === 'cohort') {
                    const cohortId = Number(property.value)
                    return `cohorts: ${
                        property.value === 'all'
                            ? 'all users'
                            : cohortId in cohortsById
                            ? cohortsById[cohortId]?.name
                            : `ID ${cohortId}`
                    }`
                }
            })
            .filter((property) => !!property)
            .join(' & ')
        summary += `${summary ? ', on ' : ''}${propertiesSummary}`
    }

    return summary.trim() || null
}

export async function updateRecording(
    recording: Partial<SessionRecordingType> & Pick<SessionRecordingType, 'id'>,
    params?: Record<string, any>,
    callback?: (recording: SessionRecordingType) => void
): Promise<SessionRecordingType> {
    const updatedRecording = await api.recordings.updateRecording(recording.id, recording, toParams(params ?? {}))
    callback?.(updatedRecording)
    return updatedRecording
}
