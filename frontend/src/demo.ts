/* eslint-disable no-console */
/**
 * Test that capture() provides type safety for defined events and flexibility for undefined events
 * and captureRaw() bypasses all type checking
 */
import posthog, { EventName } from './lib/posthog-typed'

// ========================================
// TEST: capture() with type safety for defined events
// ========================================

// ✅ Should work - all properties provided
posthog.capture('downloaded_file', {
    file_name: 'report.pdf',
    file_size_b: 1024000,
    file_type: 'application/pdf',
})

// ✅ Should work - only required property
posthog.capture('downloaded_file', {
    file_size_b: 512000,
})

// ✅ Should work - additional properties allowed
posthog.capture('downloaded_file', {
    file_size_b: 2048000,
    file_name: 'data.csv',
    file_type: 'text/csv',
    download_speed: 'fast',
    custom_field: 'extra data',
})

// ✅ Should work - uploaded_file with all properties
posthog.capture('uploaded_file', {
    file_name: 'avatar.png',
    file_size_b: 204800,
    file_type: 'image/png',
})

// ✅ Should work - events with all optional properties (no properties needed)
posthog.capture('logged_out')
posthog.capture('signed_up')
posthog.capture('user logged in')

// ✅ Should work - events with all optional properties (with properties)
posthog.capture('logged_out', {
    custom_reason: 'user initiated',
})

// ✅ Should work - insight events with optional properties
posthog.capture('insight viewed', {
    insight_id: 'abc123',
    insight_type: 'trends',
})

posthog.capture('insight created', {
    insight_type: 'funnel',
    dashboard_id: 'def456',
})

// ❌ Should error - missing required property 'file_size_b'
// @ts-expect-error - missing required property
posthog.capture('downloaded_file', {
    file_name: 'data.csv',
})

// ❌ Should error - wrong type for file_size_b (string instead of number)
// @ts-expect-error - wrong type for file_size_b
posthog.capture('downloaded_file', {
    file_size_b: '1024000',
})

// ❌ Should error - string typed variable with defined event name
let a: string = 'downloaded_file'
// @ts-expect-error - string variable not allowed
posthog.capture(a)

// ========================================
// TEST: capture() with flexibility for undefined events
// ========================================

// ✅ Should work - undefined event with arbitrary properties
posthog.capture('Any Random Event Name', {
    any: 'properties',
    work: 'here',
})

// ✅ Should work - undefined event with no properties
posthog.capture('Simple Event')
posthog.capture('Event With Null', null)

// ========================================
// TEST: Using variables with capture()
// ========================================

// ❌ This doesn't work - string typed variable with defined event name causes error
let invalidVariable = 'downloaded_file'
// @ts-expect-error - string variable not allowed
posthog.capture(invalidVariable) // Error: Type 'string' is not assignable to type 'never'

// ✅ Fix 1: Explicitly type the variable as EventName
let validVariable: EventName = 'downloaded_file'
posthog.capture(validVariable, {
    file_size_b: 1024,
})

// ✅ Fix 2: Use const for literal type inference
const literalVariable = 'uploaded_file'
posthog.capture(literalVariable, {
    file_size_b: 2048,
    file_name: 'document.pdf',
})

// ✅ Fix 3: Use captureRaw() to bypass type checking
const stringVariable = 'downloaded_file'
posthog.captureRaw(stringVariable, {
    file_size_b: 1024,
})

// ❌ Dynamic event names are inferred as 'string' type, so they error with capture()
const dynamicEventName = 'custom_' + Math.random()
// @ts-expect-error - dynamic string inferred as 'string' type
posthog.capture(dynamicEventName, {
    timestamp: Date.now(),
})

// ✅ Fix: Use captureRaw() for dynamic event names
const dynamicEventName2 = 'custom_' + Math.random()
posthog.captureRaw(dynamicEventName2, {
    timestamp: Date.now(),
})

// ========================================
// TEST: captureRaw() bypasses all type checking
// ========================================

// ✅ All of these should work with captureRaw (no type safety)
posthog.captureRaw('downloaded_file', {
    file_name: 'data.csv',
    // Missing required file_size_b is OK with captureRaw
})

posthog.captureRaw('downloaded_file', {
    file_size_b: 'string is OK here',
    file_name: 1234, // any type is OK
})

posthog.captureRaw('Any Event Name', {
    any: 'properties',
    work: 'here',
})

// ✅ Variables with string type work with captureRaw
const rawVariable = 'downloaded_file'
posthog.captureRaw(rawVariable, {
    file_size_b: 2048,
})

// ========================================
// TEST: PostHog system events
// ========================================

// ✅ $pageview - manually captured in SPAs
posthog.capture('$pageview', {
    url: window.location.href,
    referrer: document.referrer,
    title: document.title,
})

// ✅ $pageleave - manually captured for session tracking
posthog.capture('$pageleave', {
    url: window.location.href,
    duration_ms: 5000,
})

// ❌ These system events are NOT available in capture() type-safe mode (by design):
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
// You can still capture these with posthog.captureRaw() if needed for edge cases
