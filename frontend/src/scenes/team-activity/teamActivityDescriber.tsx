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

import {
    ActivityScope,
    CorrelationConfigType,
    GroupType,
    PathCleaningFilter,
    TeamSurveyConfigType,
    TeamType,
} from '~/types'

import { ThemeName } from '../dataThemeLogic'
import { marketingAnalyticsConfigurationDescriber } from './marketing_analytics_config/marketingAnalyticsConfigurationDescriber'
import { revenueAnalyticsConfigurationDescriber } from './revenue_analytics_config/revenueAnalyticsConfigurationDescriber'
import { CURRENCY_SYMBOL_TO_EMOJI_MAP, CURRENCY_SYMBOL_TO_NAME_MAP } from 'lib/utils/geography/currency'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { PathCleanFilterItem } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { keyFromFilter } from 'lib/components/PathCleanFilters/PathCleanFilters'

// Helper functions for common change description patterns
function createBooleanToggleHandler(featureName: string, options: { verb?: [string, string] } = {}) {
    return (change: ActivityChange): ChangeMapping | null => {
        const { verb = ['enabled', 'disabled'] } = options

        const [enabledVerb, disabledVerb] = verb
        const verbText = change.after ? enabledVerb : disabledVerb

        return {
            description: [
                <>
                    {verbText} {featureName}
                </>,
            ],
        }
    }
}

function createSessionRecordingConfigHandler(configName: string) {
    return (change: ActivityChange): ChangeMapping | null => {
        if (change.before === null && change.after === null) {
            return null
        }
        return {
            description: [<>Changed session replay {configName}</>],
        }
    }
}

function createApiTokenHandler(tokenType: string, createdVerb: string, changedVerb: string) {
    return (change: ActivityChange): ChangeMapping | null => {
        if (change.after === undefined) {
            return null
        }

        const prefix = change.action === 'created' ? createdVerb : changedVerb
        return {
            description: [
                <>
                    {prefix} the {tokenType}
                </>,
            ],
        }
    }
}

function createArrayChangeHandler(
    fieldName: string,
    options: { useEmphasis?: boolean; map?: (item: any) => string | null | undefined } = {}
) {
    return (change: ActivityChange): ChangeMapping | null => {
        const { useEmphasis = true, map } = options

        if (change.after === undefined) {
            return null
        }

        const array = change.after as any[]
        const displayArray = map ? array.map(map).filter(Boolean) : array
        const fieldNameElement = useEmphasis ? <em>{fieldName}</em> : fieldName

        return {
            description: [
                <>
                    {change.action === 'created' ? 'set' : 'changed'} the {fieldNameElement} to{' '}
                    <code>[{displayArray.join(', ')}]</code>
                </>,
            ],
        }
    }
}

function createSimpleValueHandler(fieldName: string, options: { useEmphasis?: boolean; requireValue?: boolean } = {}) {
    return (change: ActivityChange): ChangeMapping | null => {
        const { useEmphasis = false, requireValue = true } = options

        if (requireValue && !change.after) {
            return null
        }

        const valueElement = useEmphasis ? <em>{change.after}</em> : change.after
        return {
            description: [
                <>
                    {change.action === 'created' ? 'set' : 'changed'} the {fieldName} to {valueElement}
                </>,
            ],
        }
    }
}

function createFixedVerbValueHandler(
    verb: string,
    fieldName: string,
    options: { useEmphasis?: boolean; checkBothNull?: boolean } = {}
) {
    return (change: ActivityChange): ChangeMapping | null => {
        const { useEmphasis = false, checkBothNull = false } = options

        if (checkBothNull && change.before === null && change.after === null) {
            return null
        }

        const valueElement = useEmphasis ? <em>{change.after}</em> : change.after
        return {
            description: [
                <>
                    {verb} {fieldName} to {valueElement}
                </>,
            ],
        }
    }
}

const TEAM_PROPERTIES_MAPPING: Record<keyof TeamType, (change: ActivityChange) => ChangeMapping | null> = {
    // API-related tokens
    api_token: createApiTokenHandler('project API key', 'set', 'reset'),
    secret_api_token: createApiTokenHandler('Feature Flags secure API key', 'generated', 'rotated'),
    secret_api_token_backup: (change) => {
        if (change.after === undefined || change.action !== 'deleted') {
            return null
        }

        return {
            description: [<>Deleted the Feature Flags secure API key backup</>],
        }
    },

    // Session replay config
    session_recording_url_trigger_config: createSessionRecordingConfigHandler('URL triggers'),
    session_recording_url_blocklist_config: createSessionRecordingConfigHandler('URL blocklist'),
    session_recording_event_trigger_config: createSessionRecordingConfigHandler('event triggers'),
    session_recording_trigger_match_type_config: createFixedVerbValueHandler(
        'Changed',
        'session replay trigger match type',
        { checkBothNull: true }
    ),
    capture_console_log_opt_in: createBooleanToggleHandler('console log capture in session replay'),
    capture_performance_opt_in: createBooleanToggleHandler('console network performance capture in session replay'),
    capture_dead_clicks: createBooleanToggleHandler('dead clicks autocapture'),
    session_recording_opt_in: createBooleanToggleHandler('session recording'),
    session_recording_minimum_duration_milliseconds: (change) => {
        const after = change.after
        if (after === undefined || typeof after !== 'number') {
            return null
        }

        let prefix = 'changed'
        if (change.action === 'created') {
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
    recording_domains: (change) => {
        const before: string[] | null = Array.isArray(change.before) ? change.before.map(String) ?? null : null
        const after: string[] | null = Array.isArray(change.after) ? change.after.map(String) ?? null : null
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
    session_recording_linked_flag: (change) => {
        const key = (change.after as any)?.key ?? (change.before as any)?.key ?? String(change.after)
        return {
            description: [
                <>
                    {change?.after ? 'linked' : 'unlinked'} session recording to feature flag {key}
                </>,
            ],
        }
    },
    session_recording_masking_config: (change) => {
        const maskAllInputsBefore = isObject(change.before) ? change.before.maskAllInputs : !!change.before
        const maskAllInputsAfter = isObject(change.after) ? change.after.maskAllInputs : !!change.after
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
    session_recording_network_payload_capture_config: (change) => {
        const payloadBefore = isObject(change.before) ? change.before.recordBody : !!change.before
        const payloadAfter = isObject(change.after) ? change.after.recordBody : !!change.after
        const payloadChanged = payloadBefore !== payloadAfter

        const headersBefore = isObject(change.before) ? change.before.recordHeaders : !!change.before
        const headersAfter = isObject(change.after) ? change.after.recordHeaders : !!change.after
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
    session_recording_sample_rate: (change) => {
        return {
            description: [
                <>
                    {change.action === 'created' ? 'set' : 'changed'} the session recording sample rate to{' '}
                    {change.after}%
                </>,
            ],
        }
    },
    session_replay_config: (change) => {
        // TODO we'll eventually need a deeper mapping for this nested object
        const after = change.after
        const recordCanvasAfter =
            after && typeof after === 'object' && !Array.isArray(after) ? after.record_canvas : null

        if (recordCanvasAfter === null) {
            return null
        }
        return { description: [<>{recordCanvasAfter ? 'enabled' : 'disabled'} canvas recording in session replay</>] }
    },

    // Survey config
    surveys_opt_in: createBooleanToggleHandler('surveys'),
    survey_config: (change) => {
        const before = change.before as TeamSurveyConfigType
        const after = change.after as TeamSurveyConfigType
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

    // Autocapture
    autocapture_exceptions_errors_to_ignore: createArrayChangeHandler('autocapture exceptions errors to ignore'),
    autocapture_exceptions_opt_in: createBooleanToggleHandler('exception autocapture'),
    autocapture_web_vitals_opt_in: createBooleanToggleHandler('web vitals autocapture'),
    autocapture_opt_out: createBooleanToggleHandler('autocapture', { verb: ['opted out of', 'opted in to'] }),
    heatmaps_opt_in: createBooleanToggleHandler('heatmaps'),
    autocapture_web_vitals_allowed_metrics: (change) => {
        const after = change.after
        const metricsList = Array.isArray(after) ? after.join(', ') : 'CLS, FCP, INP, and LCP'
        return { description: [<>set allowed web vitals autocapture metrics to {metricsList}</>] }
    },

    // and.... many more random stuff
    name: createSimpleValueHandler('team name', { requireValue: false }),
    test_account_filters_default_checked: createBooleanToggleHandler(
        '"internal & test account filters" for all insights'
    ),
    anonymize_ips: createBooleanToggleHandler('anonymizing IP addresses'),
    slack_incoming_webhook: createSimpleValueHandler('Slack incoming webhook'),
    timezone: createSimpleValueHandler('timezone', { useEmphasis: true }),
    data_attributes: createArrayChangeHandler('data attributes'),
    live_events_columns: createArrayChangeHandler('live events columns'),
    app_urls: createArrayChangeHandler('app URLs'),
    group_types: createArrayChangeHandler('group types', { map: (group: GroupType) => group.name_plural }),
    person_display_name_properties: createArrayChangeHandler('person display name properties'),
    person_on_events_querying_enabled: createBooleanToggleHandler('querying person on events'),
    human_friendly_comparison_periods: createBooleanToggleHandler('human friendly comparison periods'),
    test_account_filters: (change) => {
        // change.after is an array of property filters
        // change.before is an array o property filters
        // so we can say what was removed and what was added
        const afters = Array.isArray(change.after) ? change.after || [] : []
        const befores = Array.isArray(change.before) ? change.before || [] : []

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
    extra_settings: (change) => {
        const after = change.after
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
    modifiers: (change) => {
        const after = change.after
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
    default_data_theme: (change) => {
        return {
            description: [
                <>
                    changed the default color theme{' '}
                    {change.before && (
                        <>
                            from <ThemeName id={change.before as number} />{' '}
                        </>
                    )}
                    to{' '}
                    <em>
                        <ThemeName id={change.after as number} />
                    </em>
                </>,
            ],
        }
    },
    base_currency: (change) => {
        const before = change.before as CurrencyCode
        const after = change.after as CurrencyCode

        return {
            description: [
                <>
                    changed the <em>base currency</em> from{' '}
                    <strong>
                        {CURRENCY_SYMBOL_TO_EMOJI_MAP[before]}&nbsp;{before}
                    </strong>{' '}
                    ({CURRENCY_SYMBOL_TO_NAME_MAP[before]}) to{' '}
                    <strong>
                        {CURRENCY_SYMBOL_TO_EMOJI_MAP[after]}&nbsp;{after}
                    </strong>{' '}
                    ({CURRENCY_SYMBOL_TO_NAME_MAP[after]})
                </>,
            ],
        }
    },
    completed_snippet_onboarding: (change) => {
        if (!change.after) {
            return null
        }

        return {
            description: [<>completed their onboarding</>],
        }
    },
    week_start_day: (change) => {
        if (change.after === undefined || change.after === null) {
            return null
        }

        const dayOfWeekMapping = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

        return {
            description: [
                <>
                    {change.action === 'created' ? 'set' : 'changed'} the week start day to{' '}
                    <em>{dayOfWeekMapping[change.after as number]}</em>
                </>,
            ],
        }
    },
    primary_dashboard: (change) => {
        if (!change.after) {
            return null
        }

        return {
            description: [
                <>
                    {change.action === 'created' ? 'set' : 'changed'} the <em>primary dashboard</em> to{' '}
                    <Link to={urls.dashboard(change.after as number)}>
                        <em>{change.after}</em>
                    </Link>
                </>,
            ],
        }
    },
    flags_persistence_default: (change) => {
        return {
            description: [
                <>
                    {change.after ? 'enabled' : 'disabled'}{' '}
                    <Link
                        to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                        target="_blank"
                    >
                        flag persistence
                    </Link>{' '}
                    by default
                </>,
            ],
        }
    },
    path_cleaning_filters: (change) => {
        if (change.after === undefined) {
            return null
        }

        return {
            description: [
                <>
                    set the <em>path cleaning filters</em> to{' '}
                    {(change.after as PathCleaningFilter[]).map((filter) => (
                        <PathCleanFilterItem key={keyFromFilter(filter)} filter={filter} />
                    ))}
                </>,
            ],
        }
    },
    onboarding_tasks: (change) => {
        const afterTasks = change.after ? Object.entries(change.after) : []
        const changedTasks = afterTasks.filter(([key, value]) => {
            const beforeValue = (change.before as { [key: string]: string })?.[key]
            return beforeValue !== value
        })

        if (!changedTasks.length) {
            return null
        }

        return {
            description: [
                <>
                    {changedTasks.map(([key, value], index) => (
                        <span key={key}>
                            {index > 0 && <>, </>}
                            {value === 'completed' ? 'completed' : 'uncompleted'} onboarding task <em>{key}</em>
                        </span>
                    ))}
                </>,
            ],
        }
    },
    has_completed_onboarding_for: (change) => {
        const beforeProducts: { [key: string]: boolean } = (change.before as { [key: string]: boolean }) || {}
        const afterProducts: { [key: string]: boolean } = (change.after as { [key: string]: boolean }) || {}

        const newlyCompletedProducts = Object.entries(afterProducts).filter(
            ([product, completed]) => completed && !beforeProducts[product]
        )

        if (!newlyCompletedProducts.length) {
            return null
        }

        return {
            description: [
                <>
                    completed onboarding for{' '}
                    {newlyCompletedProducts.map(([product], index) => (
                        <span key={product}>
                            {index > 0 && <>, </>}
                            <strong>{product}</strong>
                        </span>
                    ))}
                </>,
            ],
        }
    },
    correlation_config: (change) => {
        const before = change.before as CorrelationConfigType
        const after = change.after as CorrelationConfigType

        const descriptions = []

        const sameArray = (a: string[], b: string[]): boolean => {
            if (a.length !== b.length) {
                return false
            }
            return a.every((x) => b.includes(x)) && b.every((x) => a.includes(x))
        }

        if (
            after.excluded_person_property_names &&
            !sameArray(before.excluded_person_property_names || [], after.excluded_person_property_names)
        ) {
            descriptions.push(
                <>
                    set <em>excluded person properties</em> to{' '}
                    <code>{after.excluded_person_property_names.join(', ')}</code>
                </>
            )
        }

        if (
            after.excluded_event_property_names &&
            !sameArray(before.excluded_event_property_names || [], after.excluded_event_property_names)
        ) {
            descriptions.push(
                <>
                    set <em>excluded event properties</em> to{' '}
                    <code>{after.excluded_event_property_names.join(', ')}</code>
                </>
            )
        }

        if (after.excluded_event_names && !sameArray(before.excluded_event_names || [], after.excluded_event_names)) {
            descriptions.push(
                <>
                    set <em>excluded event names</em> to <code>{after.excluded_event_names.join(', ')}</code>
                </>
            )
        }

        return { description: descriptions }
    },

    // Complex configs that require a custom describer
    marketing_analytics_config: marketingAnalyticsConfigurationDescriber,
    revenue_analytics_config: revenueAnalyticsConfigurationDescriber,

    // should never come from the backend
    created_at: () => null,
    id: () => null,
    updated_at: () => null,
    uuid: () => null,
    user_access_level: () => null,
    live_events_token: () => null,
    product_intents: () => null,
    cookieless_server_hash_mode: () => null,

    // don't make sense to be displayed
    project_id: () => null,
    organization: () => null,
    ingested_event: () => null,
    effective_membership_level: () => null,
    default_modifiers: () => null,
    is_demo: () => null,
    access_control: () => null,
    has_group_types: () => null,
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
            if (!change?.field || !(change.field in TEAM_PROPERTIES_MAPPING)) {
                continue //  not all fields are describable
            }

            const actionHandler = TEAM_PROPERTIES_MAPPING[change.field as keyof TeamType]
            const processedChange = actionHandler(change)
            if (processedChange === null) {
                continue // some logs are indescribable
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
