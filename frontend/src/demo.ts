/* eslint-disable no-console */
/**
 * Test that captureTyped() provides type safety and capture() is flexible
 */
import posthog, { EventName } from './lib/posthog-typed'

// ========================================
// TEST: captureTyped() with type safety
// ========================================

// ✅ Should work - all properties provided
posthog.captureTyped('downloaded_file', {
    file_name: 'report.pdf',
    file_size_b: 1024000,
    file_type: 'application/pdf',
})

// ✅ Should work - only required property
posthog.captureTyped('downloaded_file', {
    file_size_b: 512000,
})

// ✅ Should work - additional properties allowed
posthog.captureTyped('downloaded_file', {
    file_size_b: 2048000,
    file_name: 'data.csv',
    file_type: 'text/csv',
    download_speed: 'fast',
    custom_field: 'extra data',
})

// ✅ Should work - uploaded_file with all properties
posthog.captureTyped('uploaded_file', {
    file_name: 'avatar.png',
    file_size_b: 204800,
    file_type: 'image/png',
})

// ✅ Should work - events with all optional properties (no properties needed)
posthog.captureTyped('logged_out')
posthog.captureTyped('signed_up')
posthog.captureTyped('user logged in')

// ✅ Should work - events with all optional properties (with properties)
posthog.captureTyped('logged_out', {
    custom_reason: 'user initiated',
})

// ✅ Should work - insight events with optional properties
posthog.captureTyped('insight viewed', {
    insight_id: 'abc123',
    insight_type: 'trends',
})

posthog.captureTyped('insight created', {
    insight_type: 'funnel',
    dashboard_id: 'def456',
})

// ❌ Should error - missing required property 'file_size_b'
posthog.captureTyped('downloaded_file', {
    file_name: 'data.csv',
})

// ❌ Should error - wrong type for file_size_b (string instead of number)
posthog.captureTyped('downloaded_file', {
    file_size_b: '1024000',
})

// ❌ Should error - unknown event name
posthog.captureTyped('Unknown Event', {
    some: 'data',
})

// ========================================
// TEST: Using variables with captureTyped
// ========================================

// ❌ This doesn't work - inferred as 'string', not a specific event
let invalidVariable = 'downloaded_file'
posthog.captureTyped(invalidVariable) // Error: string not assignable to EventName

// ✅ Fix 1: Explicitly type the variable as EventName
let validVariable: EventName = 'downloaded_file'
posthog.captureTyped(validVariable, {
    file_size_b: 1024,
})

// ✅ Fix 2: Use const for literal type inference
const literalVariable = 'uploaded_file'
posthog.captureTyped(literalVariable, {
    file_size_b: 2048,
    file_name: 'document.pdf',
})

// ========================================
// TEST: capture() is flexible (untyped)
// ========================================

// ✅ All of these should work with capture
posthog.capture('downloaded_file', {
    file_size_b: 1024,
    file_name: 'report.pdf',
})

posthog.capture('downloaded_file', {
    file_name: 'data.csv',
    // Missing required file_size_b is OK with untyped capture
})

posthog.capture('downloaded_file', {
    file_size_b: 'string is OK here',
    file_name: 1234, // any type is OK
})

posthog.capture('Any Random Event Name', {
    any: 'properties',
    work: 'here',
})

posthog.capture('Simple Event')
posthog.capture('Event With Null', null)

// ✅ Dynamic event names work with capture
const dynamicEventName = 'custom_' + Math.random()
posthog.capture(dynamicEventName, {
    timestamp: Date.now(),
})

// ========================================
// TEST: PostHog system events
// ========================================

// ✅ $pageview - manually captured in SPAs
posthog.captureTyped('$pageview', {
    url: window.location.href,
    referrer: document.referrer,
    title: document.title,
})

// ✅ $pageleave - manually captured for session tracking
posthog.captureTyped('$pageleave', {
    url: window.location.href,
    duration_ms: 5000,
})

// ✅ $screen - manually captured in mobile apps (iOS, Android, React Native, Flutter)
posthog.captureTyped('$screen', {
    screen_name: 'Dashboard',
    screen_class: 'DashboardViewController',
})

posthog.captureTyped('$screen', {
    screen_name: 'Settings',
    previous_screen: 'Dashboard',
    user_id: '123',
})

// ❌ These system events are NOT available in captureTyped (by design):
// - $autocapture - Automatically captured by posthog-js
// - $exception - Automatically captured by posthog-js
// - $rageclick - Automatically captured by posthog-js
// - $web_vitals - Automatically captured by posthog-js
// - $identify - Use posthog.identify() method instead
// - $groupidentify - Use posthog.group() method instead
// - $set - Not an event, it's a property you include in events
// - $feature_flag_called - Internal PostHog tracking only
// - $opt_in - Use posthog.opt_in_capturing() method instead
//
// You can still capture these with posthog.capture() if needed for edge cases

// ========================================
// TEST: Query and insight events
// ========================================

posthog.captureTyped('query executed', {
    query_type: 'trends',
    duration_ms: 234,
})

posthog.captureTyped('query completed', {
    query_id: 'q123',
    success: true,
})

posthog.captureTyped('query failed', {
    query_id: 'q456',
    error: 'timeout',
})

posthog.captureTyped('dashboard refreshed', {
    dashboard_id: 'd789',
    insights_count: 12,
})
