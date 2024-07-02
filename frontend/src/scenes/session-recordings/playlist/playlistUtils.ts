import { router } from 'kea-router'
import api from 'lib/api'
import { convertPropertyGroupToProperties, isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { UniversalFilterValue } from 'lib/components/UniversalFilters/UniversalFilters'
import { isActionFilter, isEventFilter } from 'lib/components/UniversalFilters/utils'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCoreFilterDefinition } from 'lib/taxonomy'
import { genericOperatorMap } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { openBillingPopupModal } from 'scenes/billing/BillingPopup'
import { toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { DEFAULT_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { PLAYLIST_LIMIT_REACHED_MESSAGE } from 'scenes/session-recordings/sessionReplaySceneLogic'
import { urls } from 'scenes/urls'

import { cohortsModelType } from '~/models/cohortsModelType'
import { PropertyOperator, SessionRecordingPlaylistType } from '~/types'

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
    try {
        playlist.filters = playlist.filters || DEFAULT_RECORDING_FILTERS
        const res = await api.recordings.createPlaylist(playlist)
        if (redirect) {
            router.actions.push(urls.replayPlaylist(res.short_id))
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

export async function deletePlaylist(
    playlist: SessionRecordingPlaylistType,
    undoCallback?: () => void
): Promise<SessionRecordingPlaylistType> {
    await deleteWithUndo({
        object: playlist,
        idField: 'short_id',
        endpoint: `projects/@current/session_recording_playlists`,
        callback: undoCallback,
    })
    return playlist
}
