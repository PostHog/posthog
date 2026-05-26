import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { projectLogic } from 'scenes/projectLogic'
import { SavedFiltersTaxonomicGroup } from 'scenes/session-recordings/filters/SavedFiltersTaxonomicGroup'
import { teamLogic } from 'scenes/teamLogic'

import { getFilterLabel } from '~/taxonomy/helpers'
import { PropertyFilterType, SessionRecordingPlaylistType } from '~/types'

import type { replayTaxonomicGroupsLogicType } from './replayTaxonomicGroupsLogicType'

export const replayTaxonomicGroupsLogic = kea<replayTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'replayTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [teamLogic, ['currentTeam'], projectLogic, ['currentProjectId']],
    })),

    selectors({
        replayTaxonomicGroups: [
            (s) => [s.currentTeam, s.currentProjectId],
            (currentTeam, projectId): TaxonomicFilterGroup[] => {
                const teamId = currentTeam?.id
                return [
                    {
                        name: 'Replay',
                        searchPlaceholder: 'Replay',
                        type: TaxonomicFilterGroupType.Replay,
                        options: [
                            {
                                key: 'visited_page',
                                name: getFilterLabel('visited_page', TaxonomicFilterGroupType.Replay),
                                propertyFilterType: PropertyFilterType.Recording,
                            },
                            {
                                key: 'snapshot_source',
                                name: getFilterLabel('snapshot_source', TaxonomicFilterGroupType.Replay),
                                propertyFilterType: PropertyFilterType.Recording,
                            },
                            {
                                key: 'level',
                                name: getFilterLabel('level', TaxonomicFilterGroupType.LogEntries),
                                propertyFilterType: PropertyFilterType.LogEntry,
                            },
                            {
                                key: 'message',
                                name: getFilterLabel('message', TaxonomicFilterGroupType.LogEntries),
                                propertyFilterType: PropertyFilterType.LogEntry,
                            },
                            {
                                key: 'comment_text',
                                name: getFilterLabel('comment_text', TaxonomicFilterGroupType.Replay),
                                propertyFilterType: PropertyFilterType.Recording,
                            },
                        ],
                        getName: (option: Record<string, any>) => option.name,
                        getValue: (option: Record<string, any>) => option.key,
                        valuesEndpoint: (key) => {
                            if (key === 'visited_page') {
                                return (
                                    `api/environments/${teamId}/events/values/?key=` +
                                    encodeURIComponent('$current_url') +
                                    '&event_name=' +
                                    encodeURIComponent('$pageview')
                                )
                            }
                        },
                        getPopoverHeader: () => 'Replay',
                    },
                    {
                        name: 'Saved filters',
                        searchPlaceholder: 'saved filters',
                        type: TaxonomicFilterGroupType.ReplaySavedFilters,
                        endpoint: combineUrl(`api/projects/${projectId}/session_recording_playlists/`, {
                            type: 'filters',
                            order: '-last_modified_at',
                        }).url,
                        render: SavedFiltersTaxonomicGroup,
                        getName: (filter: SessionRecordingPlaylistType) =>
                            filter.name || filter.derived_name || 'Unnamed',
                        getValue: (filter: SessionRecordingPlaylistType) => filter.short_id,
                        getPopoverHeader: () => 'Saved filter',
                    },
                ]
            },
        ],
    }),
])
