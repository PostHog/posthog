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
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { Link } from 'lib/lemon-ui/Link'
import { isObject, pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ActivityScope, TeamSurveyConfigType, TeamType } from '~/types'

import { ThemeName } from './dataThemeLogic'

const teamActionsMapping: Record<
    keyof TeamType,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    api_token: (change) => {
        if (change === undefined || change.after === undefined) {
            return null
        }
        const prefix = change.action === 'created' ? 'set' : 'reset'
        return {
            description: [<>{prefix} the project API key</>],
        }
    },
    secret_api_token: (change) => {
        if (change === undefined || change.after === undefined) {
            return null
        }
        const prefix = change.action === 'created' ? 'generated' : 'rotated'
        return {
            description: [<>{prefix} the Feature Flags secure API key</>],
        }
    },
    secret_api_token_backup: (change) => {
        if (change === undefined || change.after === undefined || change.action !== 'deleted') {
            return null
        }
        return {
            description: [<>Deleted the Feature Flags secure API key backup</>],
        }
    },

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
    session_recording_url_trigger_config(change: ActivityChange | undefined): ChangeMapping | null {
        const before = change?.before
        const after = change?.after
        if (before === null && after === null) {
            return null
        }

        return {
            description: [<>Changed session replay URL triggers</>],
        }
    },
    session_recording_url_blocklist_config(change: ActivityChange | undefined): ChangeMapping | null {
        const before = change?.before
        const after = change?.after
        if (before === null && after === null) {
            return null
        }

        return {
            description: [<>Changed session replay URL blocklist</>],
        }
    },
    session_recording_event_trigger_config(change: ActivityChange | undefined): ChangeMapping | null {
        const before = change?.before
        const after = change?.after
        if (before === null && after === null) {
            return null
        }

        return {
            description: [<>Changed session replay event triggers</>],
        }
    },
    session_recording_trigger_match_type_config(change: ActivityChange | undefined): ChangeMapping | null {
        const before = change?.before
        const after = change?.after
        if (before === null && after === null) {
            return null
        }
        return {
            description: [<>Changed session replay trigger match type to {after}</>],
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
    capture_dead_clicks(change: ActivityChange | undefined): ChangeMapping | null {
        return {
            description: [<>{change?.after ? 'enabled' : 'disabled'} dead clicks autocapture</>],
        }
    },
    recording_domains(change: ActivityChange | undefined): ChangeMapping | null {
        const before: string[] | null = Array.isArray(change?.before) ? change?.before.map(String) ?? null : null
        const after: string[] | null = Array.isArray(change?.after) ? change?.after.map(String) ?? null : null
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
                    {pluralize(adds.length, 'domain', 'domains', false)}
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
                    {pluralize(removes.length, 'domain', 'domains', false)}
                </>
            )
        }
        return { description: descriptions }
    },
    session_recording_linked_flag(change: ActivityChange | undefined): ChangeMapping | null {
        const key = (change?.after as any)?.key ?? (change?.before as any)?.key ?? String(change?.after)
        return {
            description: [
                <>
                    {change?.after ? 'linked' : 'unlinked'} session recording to feature flag {key}
                </>,
            ],
        }
    },
    session_recording_masking_config(change: ActivityChange | undefined): ChangeMapping | null {
        const maskAllInputsBefore = isObject(change?.before) ? change?.before.maskAllInputs : !!change?.before
        const maskAllInputsAfter = isObject(change?.after) ? change?.after.maskAllInputs : !!change?.after
        const maskAllInputsChanged = maskAllInputsBefore !== maskAllInputsAfter

        const blockSelectorBefore = isObject(change?.before) ? change?.before.blockSelector : undefined
        const blockSelectorAfter = isObject(change?.after) ? change?.after.blockSelector : undefined
        const blockSelectorChanged = blockSelectorBefore !== blockSelectorAfter

        const maskTextSelectorBefore = isObject(change?.before) ? change?.before.maskTextSelector : !!change?.before
        const maskTextSelectorAfter = isObject(change?.after) ? change?.after.maskTextSelector : !!change?.after
        const maskTextSelectorChanged = maskTextSelectorBefore !== maskTextSelectorAfter

        const descriptions = []
        if (maskAllInputsChanged) {
            descriptions.push(<>{maskAllInputsAfter ? 'enabled' : 'disabled'} masking all inputs in session replay</>)
        }

        if (maskTextSelectorChanged) {
            descriptions.push(
                <>
                    {change?.action === 'created' ? 'set' : 'changed'} masking text selector to {maskTextSelectorAfter}{' '}
                    in session replay
                </>
            )
        }

        if (blockSelectorChanged) {
            descriptions.push(
                <>
                    {change?.action === 'created' ? 'set' : 'changed'} blocking selector to "{blockSelectorAfter}"
                </>
            )
        }

        return descriptions.length
            ? {
                  description: descriptions,
              }
            : null
    },
    session_recording_network_payload_capture_config(change: ActivityChange | undefined): ChangeMapping | null {
        const payloadBefore = isObject(change?.before) ? change?.before.recordBody : !!change?.before
        const payloadAfter = isObject(change?.after) ? change?.after.recordBody : !!change?.after
        const payloadChanged = payloadBefore !== payloadAfter

        const headersBefore = isObject(change?.before) ? change?.before.recordHeaders : !!change?.before
        const headersAfter = isObject(change?.after) ? change?.after.recordHeaders : !!change?.after
        const headersChanged = headersBefore !== headersAfter

        const descriptions = []
        if (payloadChanged) {
            descriptions.push(<>{payloadAfter ? 'enabled' : 'disabled'} network body capture in session replay</>)
        }

        if (headersChanged) {
            descriptions.push(<>{headersAfter ? 'enabled' : 'disabled'} network headers capture in session replay</>)
        }

        return descriptions.length
            ? {
                  description: descriptions,
              }
            : null
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
    survey_config: (change: ActivityChange | undefined): ChangeMapping | null => {
        const before = change!.before as TeamSurveyConfigType
        const after = change!.after as TeamSurveyConfigType
        const descriptions = []
        const preamble = 'Survey Configuration : '
        if (before === undefined) {
            descriptions.push('Survey Configuration was enabled')
        }

        const propertyChangeDesc = (
            name: string,
            callback: (config: TeamSurveyConfigType) => string | undefined
        ): void => {
            if (callback(before) !== callback(after)) {
                descriptions.push(`${preamble} ${name} was changed from "${callback(before)}" to "${callback(after)}"`)
            }
        }

        if (before?.appearance?.whiteLabel !== after?.appearance?.whiteLabel) {
            descriptions.push(
                `${preamble} Survey white labeling was ${after?.appearance?.whiteLabel ? 'enabled' : 'disabled'}`
            )
        }

        if (before?.appearance?.displayThankYouMessage !== after?.appearance?.displayThankYouMessage) {
            descriptions.push(
                `${preamble} displayThankYouMessage was ${after?.appearance?.whiteLabel ? 'enabled' : 'disabled'}`
            )
        }

        propertyChangeDesc('backgroundColor', (c) => c?.appearance?.backgroundColor)
        propertyChangeDesc('submitButtonColor', (c) => c?.appearance?.submitButtonColor)
        propertyChangeDesc('submitButtonTextColor', (c) => c?.appearance?.submitButtonTextColor)
        propertyChangeDesc('ratingButtonColor', (c) => c?.appearance?.ratingButtonColor)
        propertyChangeDesc('ratingButtonActiveColor', (c) => c?.appearance?.ratingButtonActiveColor)
        propertyChangeDesc('borderColor', (c) => c?.appearance?.borderColor)
        propertyChangeDesc('placeholder', (c) => c?.appearance?.placeholder)
        propertyChangeDesc('thankYouMessageHeader', (c) => c?.appearance?.thankYouMessageHeader)
        propertyChangeDesc('position', (c) => c?.appearance?.position)

        return { description: descriptions }
    },
    session_replay_config(change: ActivityChange | undefined): ChangeMapping | null {
        // TODO we'll eventually need a deeper mapping for this nested object
        const after = change?.after
        const recordCanvasAfter =
            after && typeof after === 'object' && !Array.isArray(after) ? after.record_canvas : null

        if (recordCanvasAfter === null) {
            return null
        }
        return { description: [<>{recordCanvasAfter ? 'enabled' : 'disabled'} canvas recording in session replay</>] }
    },
    // autocapture
    autocapture_exceptions_errors_to_ignore: () => null,
    autocapture_exceptions_opt_in(change: ActivityChange | undefined): ChangeMapping | null {
        return { description: [<>{change?.after ? 'enabled' : 'disabled'} exception autocapture</>] }
    },
    autocapture_web_vitals_opt_in(change: ActivityChange | undefined): ChangeMapping | null {
        return { description: [<>{change?.after ? 'enabled' : 'disabled'} web vitals autocapture</>] }
    },
    autocapture_web_vitals_allowed_metrics(change: ActivityChange | undefined): ChangeMapping | null {
        const after = change?.after
        const metricsList = Array.isArray(after) ? after.join(', ') : 'CLS, FCP, INP, and LCP'
        return { description: [<>set allowed web vitals autocapture metrics to {metricsList}</>] }
    },
    autocapture_opt_out(change: ActivityChange | undefined): ChangeMapping | null {
        return { description: [<>{change?.after ? 'opted out of' : 'opted in to'} autocapture</>] }
    },
    heatmaps_opt_in(change: ActivityChange | undefined): ChangeMapping | null {
        return { description: [<>{change?.after ? 'enabled' : 'disabled'} heatmaps</>] }
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
    test_account_filters: (change) => {
        // change?.after is an array of property filters
        // change?.before is an array o property filters
        // so we can say what was removed and what was added
        const afters = Array.isArray(change?.after) ? change?.after || [] : []
        const befores = Array.isArray(change?.before) ? change?.before || [] : []

        const addedFilters = afters.filter((filter) => !befores.some((before) => before.key === filter.key))

        const removedFilters = befores.filter((filter) => !afters.some((after) => after.key === filter.key))

        const listParts = []
        if (addedFilters.length) {
            listParts.push(
                <>
                    added <PropertyFiltersDisplay filters={addedFilters} />
                </>
            )
        }
        if (removedFilters.length) {
            listParts.push(
                <>
                    removed <PropertyFiltersDisplay filters={removedFilters} />
                </>
            )
        }
        if (listParts.length === 0) {
            return null
        }

        return {
            description: [
                <>Updated the "internal and test" account filters</>,
                <SentenceList key={0} listParts={listParts} />,
            ],
        }
    },
    test_account_filters_default_checked: (change) => {
        return {
            description: [
                <>{change?.after ? 'enabled' : 'disabled'} "internal & test account filters" for all insights</>,
            ],
        }
    },
    extra_settings: (change: ActivityChange | undefined): ChangeMapping | null => {
        const after = change?.after
        if (typeof after !== 'object') {
            return null
        }
        const descriptions = []
        for (const key in after) {
            if (key === 'poe_v2_enabled') {
                descriptions.push(
                    <>{after[key as keyof typeof after] ? 'enabled' : 'disabled'} Person on Events (v2)</>
                )
            }
        }
        return { description: descriptions }
    },
    modifiers: (change: ActivityChange | undefined): ChangeMapping | null => {
        const after = change?.after
        if (typeof after !== 'object') {
            return null
        }
        const descriptions = []
        for (const key in after) {
            descriptions.push(
                <>
                    set <em>{key}</em> to "{String(after[key as keyof typeof after])}"
                </>
            )
        }
        return { description: descriptions }
    },
    default_data_theme: (change): ChangeMapping | null => {
        return {
            description: [
                <>
                    changed the default color theme{' '}
                    {change?.before && (
                        <>
                            from <ThemeName id={change.before as number} />{' '}
                        </>
                    )}
                    to{' '}
                    <em>
                        <ThemeName id={change?.after as number} />
                    </em>
                </>,
            ],
        }
    },
    human_friendly_comparison_periods: (change): ChangeMapping | null => {
        if (!change) {
            return null
        }

        return {
            description: [
                <>
                    <strong>{change?.after ? 'enabled' : 'disabled'}</strong> human friendly comparison periods
                </>,
            ],
        }
    },
    surveys_opt_in: (change): ChangeMapping | null => {
        if (!change) {
            return null
        }

        return {
            description: [<>{change?.after ? 'enabled' : 'disabled'} surveys</>],
        }
    },

    // TODO implement these when possible
    access_control: () => null,
    anonymize_ips: () => null,
    app_urls: () => null,
    completed_snippet_onboarding: () => null,
    correlation_config: () => null,
    data_attributes: () => null,
    effective_membership_level: () => null,
    has_group_types: () => null,
    group_types: () => null,
    ingested_event: () => null,
    is_demo: () => null,
    live_events_columns: () => null,
    organization: () => null,
    project_id: () => null,
    path_cleaning_filters: () => null,
    person_display_name_properties: () => null,
    person_on_events_querying_enabled: () => null,
    primary_dashboard: () => null,
    slack_incoming_webhook: () => null,
    timezone: () => null,
    revenue_analytics_config: () => null,
    marketing_analytics_config: () => null,
    flags_persistence_default: () => null,
    week_start_day: () => null,
    default_modifiers: () => null,
    has_completed_onboarding_for: () => null,
    onboarding_tasks: () => null,

    // should never come from the backend
    created_at: () => null,
    id: () => null,
    updated_at: () => null,
    uuid: () => null,
    user_access_level: () => null,
    live_events_token: () => null,
    product_intents: () => null,
    cookieless_server_hash_mode: () => null,
    access_control_version: () => null,
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
            if (!change?.field || !(change.field in teamActionsMapping)) {
                continue //  not all notebook fields are describable
            }

            const actionHandler = teamActionsMapping[change.field as keyof TeamType]
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
