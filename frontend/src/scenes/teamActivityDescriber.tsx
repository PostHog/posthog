import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    defaultDescriber,
    Description,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ActivityScope, TeamType } from '~/types'

const teamActionsMapping: Record<
    keyof TeamType,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    // session replay
    session_recording_minimum_duration_milliseconds: (change) => {
        const after = change?.after
        if (after === undefined || typeof after !== 'number') {
            return null
        }
        let prefix = 'changed'
        if (change?.action === 'created') {
            prefix = 'set'
        }
        return {
            description: [
                <>
                    {prefix} the minimum session recording duration to {after / 1000} seconds
                </>,
            ],
        }
    },
    capture_console_log_opt_in(change: ActivityChange | undefined): ChangeMapping | null {
        return { description: [<>{change?.after ? 'enabled' : 'disabled'} console log capture in session replay</>] }
    },
    capture_performance_opt_in(change: ActivityChange | undefined): ChangeMapping | null {
        return {
            description: [
                <>{change?.after ? 'enabled' : 'disabled'} console network performance capture in session replay</>,
            ],
        }
    },
    recording_domains(change: ActivityChange | undefined): ChangeMapping | null {
        const before: string[] | null = Array.isArray(change?.before) ? change!.before : null
        const after: string[] | null = Array.isArray(change?.after) ? change!.after : null
        if (after === null && before === null) {
            return null
        }

        const descriptions = []

        const adds: string[] = []
        if (after) {
            for (const domain of after) {
                if ((!before || !before.includes(domain)) && domain.trim().length > 0) {
                    adds.push(domain)
                }
            }
        }
        if (adds.length) {
            descriptions.push(
                <>
                    added {adds.join(', ')} to session recording authorised{' '}
                    {pluralize(adds.length, 'domain', 'domains')}{' '}
                </>
            )
        }

        const removes: string[] = []
        if (before) {
            for (const domain of before) {
                if ((!after || !after.includes(domain)) && domain.trim().length > 0) {
                    removes.push(domain)
                }
            }
        }

        if (removes.length) {
            descriptions.push(
                <>
                    removed {removes.join(', ')} from session recording authorised{' '}
                    {pluralize(removes.length, 'domain', 'domains')}{' '}
                </>
            )
        }
        return { description: descriptions }
    },
    session_recording_linked_flag(change: ActivityChange | undefined): ChangeMapping | null {
        return {
            description: [
                <>
                    {change?.after ? 'linked' : 'unlinked'} session recording to feature flag {change?.after}
                </>,
            ],
        }
    },
    session_recording_network_payload_capture_config(change: ActivityChange | undefined): ChangeMapping | null {
        return {
            description: [<>{change?.after ? 'enabled' : 'disabled'} network payload capture in session replay</>],
        }
    },
    session_recording_opt_in(change: ActivityChange | undefined): ChangeMapping | null {
        return { description: [<>{change?.after ? 'enabled' : 'disabled'} session recording</>] }
    },
    session_recording_sample_rate(change: ActivityChange | undefined): ChangeMapping | null {
        return {
            description: [
                <>
                    {change?.action === 'created' ? 'set' : 'changed'} the session recording sample rate to{' '}
                    {change?.after}%
                </>,
            ],
        }
    },
    session_replay_config(_change: ActivityChange | undefined): ChangeMapping | null {
        // TODO we'll eventually need a deeper mapping for this nested object
        const recordCanvasAfter = typeof _change?.after === 'object' ? _change?.after?.record_canvas : null

        if (recordCanvasAfter === null) {
            return null
        }
        return { description: [<>{recordCanvasAfter ? 'enabled' : 'disabled'} canvas recording in session replay</>] }
    },
    // autocapture
    autocapture_exceptions_errors_to_ignore: () => null,
    autocapture_exceptions_opt_in: () => null,
    autocapture_opt_out(change: ActivityChange | undefined): ChangeMapping | null {
        return { description: [<>{change?.after ? 'enabled' : 'disabled'} autocapture</>] }
    },
    // and.... many more
    name(change: ActivityChange | undefined): ChangeMapping | null {
        return {
            description: [
                <>
                    {change?.action === 'created' ? 'set' : 'changed'} the team name to {change?.after}
                </>,
            ],
        }
    },
    // TODO if I had to test and describe every single one of this I'd never release this
    // we can add descriptions here as the need arises
    access_control: () => null,
    anonymize_ips: () => null,
    app_urls: () => null,
    completed_snippet_onboarding: () => null,
    correlation_config: () => null,
    data_attributes: () => null,
    effective_membership_level: () => null,
    groups_on_events_querying_enabled: () => null,
    has_group_types: () => null,
    ingested_event: () => null,
    is_demo: () => null,
    live_events_columns: () => null,
    organization: () => null,
    path_cleaning_filters: () => null,
    person_display_name_properties: () => null,
    person_on_events_querying_enabled: () => null,
    primary_dashboard: () => null,
    slack_incoming_webhook: () => null,
    test_account_filters: () => null,
    test_account_filters_default_checked: () => null,
    timezone: () => null,
    surveys_opt_in: () => null,
    week_start_day: () => null,
    extra_settings: () => null,
    has_completed_onboarding_for: () => null,
    // should never come from the backend
    created_at: () => null,
    api_token: () => null,
    id: () => null,
    updated_at: () => null,
    uuid: () => null,
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    return logItem?.detail?.short_id ? (
        <Link to={urls.notebook(logItem.detail.short_id)}>{logItem?.detail.name || 'unknown'}</Link>
    ) : logItem?.detail.name ? (
        <>{logItem?.detail.name}</>
    ) : (
        <i>Untitled</i>
    )
}

export function teamActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.TEAM) {
        console.error('team describer received a non-Team activity')
        return { description: null }
    }

    if (logItem.activity == 'changed' || logItem.activity == 'updated') {
        let changes: Description[] = []
        let changeSuffix: Description = <>on {nameAndLink(logItem)}</>

        for (const change of logItem.detail.changes || []) {
            if (!change?.field || !teamActionsMapping[change.field]) {
                continue //  not all notebook fields are describable
            }

            const actionHandler = teamActionsMapping[change.field]
            const processedChange = actionHandler(change, logItem)
            if (processedChange === null) {
                continue // // unexpected log from backend is indescribable
            }

            const { description, suffix } = processedChange
            if (description) {
                changes = changes.concat(description)
            }

            if (suffix) {
                changeSuffix = suffix
            }
        }

        if (changes.length) {
            return {
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        suffix={changeSuffix}
                    />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, nameAndLink(logItem))
}
