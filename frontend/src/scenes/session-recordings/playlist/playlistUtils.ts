import { PropertyOperator, RecordingFilters, SessionRecordingPlaylistType, SessionRecordingType } from '~/types'
import { cohortsModelType } from '~/models/cohortsModelType'
import { toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { convertPropertyGroupToProperties, deleteWithUndo, genericOperatorMap, toParams } from 'lib/utils'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'

import { openBillingPopupModal } from 'scenes/billing/v2/BillingPopup'
import api from 'lib/api'
import { PLAYLIST_LIMIT_REACHED_MESSAGE } from '../sessionRecordingsLogic'
import { lemonToast } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { DEFAULT_RECORDING_FILTERS } from './sessionRecordingsListLogic'

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

export async function createPlaylist(
    playlist: Partial<SessionRecordingPlaylistType>,
    redirect = true
): Promise<SessionRecordingPlaylistType | null> {
    try {
        playlist.filters = playlist.filters || DEFAULT_RECORDING_FILTERS
        const res = await api.recordings.createPlaylist(playlist)
        if (redirect) {
            router.actions.push(urls.sessionRecordingPlaylist(res.short_id))
        }
        return res
    } catch (e: any) {
        if (e.status === 403) {
            openBillingPopupModal({
                title: `Upgrade now to unlock unlimited playlists`,
                description: PLAYLIST_LIMIT_REACHED_MESSAGE,
            })
        } else {
            throw e
        }
    }

    return null
}

export async function duplicatePlaylist(
    playlist: Partial<SessionRecordingPlaylistType>,
    redirect = true
): Promise<SessionRecordingPlaylistType | null> {
    const { id, short_id, ...partialPlaylist } = playlist
    partialPlaylist.name = partialPlaylist.name ? partialPlaylist.name + ' (copy)' : ''
    partialPlaylist.derived_name = partialPlaylist.derived_name

    const newPlaylist = await createPlaylist(playlist, redirect)
    if (!newPlaylist) {
        return null
    }

    lemonToast.success('Playlist duplicated successfully')

    return newPlaylist
}

export async function deletePlaylistWithUndo(
    playlist: SessionRecordingPlaylistType,
    callback?: () => void
): Promise<void> {
    return deleteWithUndo({
        object: playlist,
        idField: 'short_id',
        endpoint: `projects/@current/session_recording_playlists`,
        callback,
    })
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
