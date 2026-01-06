import { CookielessServerHashMode, ProjectId, Team } from '../../src/types'
import { UUIDT } from '../../src/utils/utils'

export function createTestTeam(overrides: Partial<Team> = {}): Team {
    return {
        id: 1,
        project_id: 1 as ProjectId,
        uuid: new UUIDT().toString(),
        organization_id: 'org-uuid-123',
        name: 'Test Team',
        anonymize_ips: false,
        api_token: 'test-api-token',
        slack_incoming_webhook: null,
        session_recording_opt_in: true,
        person_processing_opt_out: false,
        heatmaps_opt_in: true,
        ingested_event: true,
        person_display_name_properties: null,
        test_account_filters: null,
        cookieless_server_hash_mode: CookielessServerHashMode.Stateful,
        timezone: 'UTC',
        available_features: [],
        drop_events_older_than_seconds: null,
        materialized_column_slots: [],
        ...overrides,
    }
}
