import { router } from 'kea-router'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { convertPropertyGroupToProperties, isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isActionFilter, isEventFilter } from 'lib/components/UniversalFilters/utils'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { genericOperatorMap } from 'lib/utils/operators'
import { toLocalFilters } from 'scenes/insights/filters/ActionFilter/legacyFilters'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { DEFAULT_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import type { cohortsModelType } from '~/models/cohortsModel'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import {
    PropertyOperator,
    RecordingUniversalFilters,
    SessionRecordingPlaylistType,
    UniversalFilterValue,
} from '~/types'

export function splitOngoingRecordings<T extends { ongoing?: boolean }>(
    recordings: T[],
    enabled: boolean
): { ongoing: T[]; finished: T[] } {
    if (!enabled || !recordings.some((r) => r.ongoing)) {
        return { ongoing: [], finished: recordings }
    }
    return { ongoing: recordings.filter((r) => r.ongoing), finished: recordings.filter((r) => !r.ongoing) }
}

// Pre-seeded session ids and the person picked from the player belong to the open list, not to a saved filter.
export function stripSessionIds<T extends Partial<RecordingUniversalFilters> | undefined | null>(filters: T): T {
    if (!filters || !('session_ids' in filters || 'person_uuid' in filters)) {
        return filters
    }
    const { session_ids: _session_ids, person_uuid: _person_uuid, ...rest } = filters
    return rest as T
}

// The list writes recommended_only false back. A saved filter never holds it.
export function comparableRecordingFilters<T extends Partial<RecordingUniversalFilters>>(filters: T): T {
    const { recommended_only, ...rest } = stripSessionIds(filters)
    return (recommended_only ? { ...rest, recommended_only } : rest) as T
}

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
    filters: UniversalFilterValue[],
    cohortsById: cohortsModelType['values']['cohortsById']
): string | null {
    const eventFilters = filters.filter(isEventFilter)
    const actionFilters = filters.filter(isActionFilter)
    const propertyFilters = filters.filter(isValidPropertyFilter)

    let summary: string
    const localFilters = toLocalFilters({ events: eventFilters, actions: actionFilters })

    summary = localFilters
        .map((localFilter) => {
            return getDisplayNameFromEntityFilter(localFilter)
        })
        .join(' & ')

    const properties = convertPropertyGroupToProperties(propertyFilters)
    if (properties && (properties.length ?? 0) > 0) {
        const propertiesSummary = properties
            .map((property) => {
                if (property.type === 'person') {
                    return `${
                        getCoreFilterDefinition(property.key, TaxonomicFilterGroupType.PersonProperties)?.label ||
                        property.key
                    } ${getOperatorSymbol(property.operator)} ${property.value}`
                }
                if (property.type === 'cohort') {
                    const cohortId = Number(property.value)
                    return `cohorts: ${cohortId in cohortsById ? cohortsById[cohortId]?.name : `ID ${cohortId}`}`
                }
            })
            .filter((property) => !!property)
            .join(' & ')
        summary += `${summary ? ', on ' : ''}${propertiesSummary}`
    }

    return summary.trim() || null
}

export async function getPlaylist(
    shortId: SessionRecordingPlaylistType['short_id']
): Promise<SessionRecordingPlaylistType> {
    return api.recordings.getPlaylist(shortId)
}

export async function updatePlaylist(
    shortId: SessionRecordingPlaylistType['short_id'],
    playlist: Partial<SessionRecordingPlaylistType>,
    silent: boolean = false
): Promise<SessionRecordingPlaylistType> {
    const newPlaylist = await api.recordings.updatePlaylist(shortId, playlist)
    refreshTreeItem('session_recording_playlist', shortId)
    if (!silent) {
        lemonToast.success('Playlist updated successfully')
    }
    return newPlaylist
}

export async function duplicatePlaylist(
    playlist: Partial<SessionRecordingPlaylistType>,
    redirect: boolean = false
): Promise<SessionRecordingPlaylistType | null> {
    const { id, short_id, ...partialPlaylist } = playlist
    partialPlaylist.name = partialPlaylist.name ? partialPlaylist.name + ' (copy)' : ''
    partialPlaylist.creation_method = 'duplicate'

    const newPlaylist = await createPlaylist(partialPlaylist, redirect)
    if (!newPlaylist) {
        return null
    }

    lemonToast.success('Playlist duplicated successfully')

    return newPlaylist
}

export async function createPlaylist(
    playlist: Partial<SessionRecordingPlaylistType>,
    redirect = false
): Promise<SessionRecordingPlaylistType | null> {
    playlist.filters = playlist.filters || DEFAULT_RECORDING_FILTERS
    if (playlist.type === 'collection') {
        playlist.filters = undefined
    }
    const res = await api.recordings.createPlaylist(playlist)
    if (playlist.type === 'collection') {
        globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateRecordingPlaylist)
    }
    if (redirect) {
        router.actions.push(urls.replayPlaylist(res.short_id))
    }
    return res
}

export async function deletePlaylist(
    playlist: SessionRecordingPlaylistType,
    undoCallback?: (undo: boolean) => void
): Promise<SessionRecordingPlaylistType> {
    await deleteWithUndo({
        object: playlist,
        idField: 'short_id',
        endpoint: `projects/${teamLogic.values.currentProjectId}/session_recording_playlists`,
        callback: (undo) => {
            if (undo) {
                refreshTreeItem('session_recording_playlist', playlist.short_id)
            } else {
                deleteFromTree('session_recording_playlist', playlist.short_id)
            }
            undoCallback?.(undo)
        },
    })
    return playlist
}
