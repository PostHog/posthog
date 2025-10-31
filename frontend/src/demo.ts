/* eslint-disable no-console */
/**
 * Type checking test file for posthog-typed.ts
 *
 * Verifies that:
 * 1. capture() validates required properties for defined events
 * 2. capture() allows additional properties beyond the schema
 * 3. capture() accepts undefined events with any properties
 * 4. capture() blocks broad string type variables
 * 5. captureRaw() bypasses all type checking
 */
import posthog, { EventName } from './lib/posthog-typed'

// ========================================
// Defined events: Type safety with flexibility
// ========================================

// ✅ Required property only
posthog.capture('downloaded_file', {
    file_size_b: 1024000,
})

// ✅ Additional properties allowed (key feature!)
posthog.capture('downloaded_file', {
    file_size_b: 2048000,
    file_name: 'data.csv',
    file_type: 'text/csv',
    download_speed: 'fast', // Not in schema
    custom_field: 'extra', // Not in schema
})

// ✅ Events with all optional properties
posthog.capture('logged_out')
posthog.capture('logged_out', { custom_reason: 'user initiated' })

// ❌ Missing required property
// @ts-expect-error
posthog.capture('downloaded_file', { file_name: 'data.csv' })

// ❌ Wrong type for required property
// @ts-expect-error
posthog.capture('downloaded_file', { file_size_b: '1024000' })

// ========================================
// Undefined events: Flexible capture
// ========================================

// ✅ Undefined events with arbitrary properties
posthog.capture('Custom Event Name', { any: 'properties', work: 'here' })
posthog.capture('Simple Event')

// ========================================
// Variable handling
// ========================================

// ❌ String type variables are blocked to prevent accidental type loss
let stringVar: string = 'downloaded_file'
// @ts-expect-error
posthog.capture(stringVar)

// ✅ Use EventName type for defined events
let typedVar: EventName = 'downloaded_file'
posthog.capture(typedVar, { file_size_b: 1024 })

// ✅ Const variables infer literal types
const constVar = 'uploaded_file'
posthog.capture(constVar, { file_size_b: 2048 })

// ✅ Dynamic event names: use captureRaw()
const dynamicEvent = 'custom_' + Math.random()
posthog.captureRaw(dynamicEvent, { timestamp: Date.now() })

// ========================================
// captureRaw: Escape hatch (no type safety)
// ========================================

// ✅ Missing required properties is OK
posthog.captureRaw('downloaded_file', { file_name: 'data.csv' })

// ✅ Wrong types are OK
posthog.captureRaw('downloaded_file', { file_size_b: 'string is OK' })

// ✅ String variables work
const rawVar = 'any_event'
posthog.captureRaw(rawVar, { any: 'data' })

// ========================================
// System events
// ========================================

// ✅ $pageview and $pageleave are whitelisted for manual capture
posthog.capture('$pageview', { url: window.location.href })
posthog.capture('$pageleave', { duration_ms: 5000 })
