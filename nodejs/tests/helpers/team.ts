import { ProjectId, Team } from '../../src/types'

/**
 * Helper function to create a Team object for tests with sensible defaults.
 *
 * @param overrides - Partial Team to override defaults
 * @returns Complete Team object
 */
export function createTestTeam(overrides: Partial<Team> = {}): Team {
    return {
        id: 1,
        uuid: 'test-team-uuid',
        organization_id: 'test-org-id',
        name: 'Test Team',
        api_token: 'test-token',
        anonymize_ips: false,
        slack_incoming_webhook: null,
        session_recording_opt_in: false,
        person_processing_opt_out: null,
        heatmaps_opt_in: null,
        ingested_event: true,
        person_display_name_properties: null,
        test_account_filters: null,
        cookieless_server_hash_mode: null,
        timezone: 'UTC',
        available_features: [],
        drop_events_older_than_seconds: null,
        project_id: 1 as unknown as ProjectId,
        ...overrides,
    }
}
