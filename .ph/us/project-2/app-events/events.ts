import { event, prop } from '@posthog/sdk/define'

// The events the app captures through frontend/src/lib/posthog-typed.ts. Properties are declared where
// the module this replaces typed them; other properties are allowed, as they were there.

// The command menu, keyboard shortcuts and navigation search.
export const commandMenu = [
    event('command k filter committed'),
    event('command k filter suggested'),
    event('command k result opened'),
    event('command k search abandoned'),
    event('command k search opened'),
    event('command menu opened'),
    event('keybind triggered'),
    event('nav search clicked'),
]

// Dashboards and their tiles.
export const dashboards = [
    event('dashboard activity summary viewed', { properties: { dashboard_id: prop.number() } }),
    event('dashboard subscribe nudge check failed', {
        properties: {
            dashboard_id: prop.number(),
            step: prop.string(),
            error_name: prop.string(),
            error_status: prop.number(),
            error_message: prop.string(),
        },
    }),
    event('dashboard subscribe nudge shown', {
        properties: { dashboard_id: prop.number(), view_count_7d: prop.number() },
    }),
    event('dashboard tile recovered from capacity error'),
]

// The data warehouse.
export const dataWarehouse = [event('data warehouse history table queried')]

// Error tracking.
export const errorTracking = [
    event('error_tracking_exception_tab_changed'),
    event('error_tracking_stacktrace_explored'),
]

// Experiment health checks.
export const experiments = [
    event('experiment health check expanded'),
    event('experiment health checked'),
    event('experiment health checks opened'),
    event('experiment health finding acted on'),
    event('experiment health finding opened'),
    event('experiment health finding shown'),
    event('experiment health rechecked'),
    event('experiment health summary opened'),
]

// Export nudges on subscriptions.
export const exports = [event('export nudge check failed'), event('export nudge not eligible')]

// Insights and the queries behind them.
export const insights = [
    event('insight empty state shown'),
    event('insight error message shown'),
    event('insight refresh hint shown'),
    event('query completed', {
        properties: {
            duration: prop.number(),
            is_cached: prop.boolean(),
            query: prop.object(),
            queryId: prop.string(),
        },
    }),
    event('query failed'),
    event('query rerun after status expired'),
]

// Releases.
export const releases = [
    event('release broadcasts auto linked'),
    event('release calendar opened'),
    event('release import failed'),
    event('release import finished'),
    event('release import started'),
    event('release item linked'),
    event('release item unlinked'),
    event('release list opened'),
    event('release merge dialog opened'),
    event('release owner changed'),
    event('release page opened'),
    event('release row expanded'),
    event('release schedule dialog opened'),
    event('release view all filtered'),
    event('release view all item opened'),
    event('release view all opened'),
    event('release view all searched'),
]

// Replay vision highlights, scanners and prompts.
export const replayVision = [
    event('replay_vision_feedback_clicked'),
    event('replay_vision_highlight_chapter_slid'),
    event('replay_vision_highlight_clip_clicked'),
    event('replay_vision_highlight_clip_dismiss_undone'),
    event('replay_vision_highlight_clip_dismissed'),
    event('replay_vision_highlight_feed_filtered'),
    event('replay_vision_highlight_feed_impressions'),
    event('replay_vision_highlight_feed_page_loaded'),
    event('replay_vision_highlight_feed_viewed'),
    event('replay_vision_highlight_picks_docs_opened'),
    event('replay_vision_highlight_picks_empty_action'),
    event('replay_vision_highlight_picks_empty_shown'),
    event('replay_vision_highlight_picks_list_mode_changed'),
    event('replay_vision_highlight_picks_shown'),
    event('replay_vision_highlight_picks_shown_third_time'),
    event('replay_vision_highlight_picks_stale_action'),
    event('replay_vision_highlight_picks_stale_shown'),
    event('replay_vision_highlight_picks_starter_failed'),
    event('replay_vision_highlight_picks_starter_settled'),
    event('replay_vision_highlight_picks_starter_started'),
    event('replay_vision_observation_link_copied'),
    event('replay_vision_prompt_used'),
    event('replay_vision_scanner_saved_filter_applied'),
    event('replay_vision_schedule_offer_accepted'),
    event('replay_vision_schedule_offer_dismissed'),
    event('replay_vision_schedule_offer_opened_scanner'),
    event('replay_vision_schedule_offer_shown'),
    event('replay_vision_watch_group_expanded'),
    event('replay_vision_watch_group_member_opened'),
    event('replay_vision_watch_group_see_all_clicked'),
]

// Restricted areas.
export const access = [event('restricted_area_accessed')]
