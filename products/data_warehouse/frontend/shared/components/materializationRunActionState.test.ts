import { EMPTY_INCREMENTAL_DRAFT } from 'scenes/data-warehouse/editor/IncrementalConfigFields'

import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import { AccessControlLevel, DataWarehouseSavedQuery } from '~/types'

import { MaterializationRunActionInputs, materializationRunActionState } from './materializationRunActionState'

const SAVED_QUERY = {
    id: 'view-1',
    name: 'orders_by_region',
    is_materialized: true,
    sync_frequency: '1hour',
    managed_viewset_kind: null,
    origin: DataWarehouseSavedQueryOrigin.DATA_WAREHOUSE,
    user_access_level: AccessControlLevel.Editor,
} as unknown as DataWarehouseSavedQuery

function stateFor(
    overrides: Partial<MaterializationRunActionInputs> = {},
    savedQueryOverrides: Partial<DataWarehouseSavedQuery> = {}
): ReturnType<typeof materializationRunActionState> {
    return materializationRunActionState({
        savedQuery: { ...SAVED_QUERY, ...savedQueryOverrides },
        kind: 'view',
        latestJobStatus: 'Completed',
        jobsLoaded: true,
        jobsError: false,
        deletingView: false,
        startingMaterialization: false,
        materializationRefreshPending: false,
        updatingDataWarehouseSavedQuery: false,
        materializationActionLoading: false,
        initialSyncFrequency: '24hour',
        incrementalDraft: EMPTY_INCREMENTAL_DRAFT,
        incrementalDraftTouched: false,
        ...overrides,
    })
}

describe('materializationRunActionState', () => {
    it.each([
        ['the run list is still loading', { jobsLoaded: false }, {}, 'Checking for a running refresh'],
        ['the run list failed to load', { jobsLoaded: false, jobsError: true }, {}, undefined],
        ['a run is in progress', { latestJobStatus: 'Running' }, {}, 'Materialization is currently running'],
        [
            'PostHog manages the view',
            {},
            { managed_viewset_kind: 'revenue_analytics' },
            'PostHog manages this view. Turn the managed viewset off to delete it.',
        ],
        [
            'an endpoint owns the view',
            {},
            { origin: DataWarehouseSavedQueryOrigin.ENDPOINT },
            'This view belongs to an endpoint. Delete the endpoint instead.',
        ],
    ] as [string, Partial<MaterializationRunActionInputs>, Partial<DataWarehouseSavedQuery>, string | undefined][])(
        'gives delete the right reason when %s',
        (_case, overrides, savedQueryOverrides, expectedReason) => {
            expect(stateFor(overrides, savedQueryOverrides).deleteReason).toEqual(expectedReason)
        }
    )

    it.each([
        ['paused', 'never', 'Scheduled refreshes are paused. Pick a cadence first, then resume.'],
        ['scheduled', '1hour', undefined],
    ])('gives a %s model the right resume reason', (_case, syncFrequency, expectedReason) => {
        expect(
            stateFor({}, { sync_frequency: syncFrequency as DataWarehouseSavedQuery['sync_frequency'] })
                .noScheduleReason
        ).toEqual(expectedReason)
    })
})
