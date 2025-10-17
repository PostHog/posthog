/**
 * Example: Typed PostHog Events
 *
 * This demonstrates the `.typed` API that provides compile-time
 * type checking for event properties based on your schema.
 *
 * HOW IT WORKS:
 * 1. Run `posthog schema pull` to generate posthog-typed.ts
 * 2. posthog-typed.ts contains:
 *    - Type augmentations for your event schemas
 *    - Re-export of posthog-js with types included
 * 3. Import from the generated file - everything just works!
 * 4. You get autocomplete and type checking for your events!
 */
// ONE IMPORT - that's it! Everything is in the generated file
import posthog from 'posthog-typed'

// The generated posthog-typed.ts file augments posthog-js like this:
// declare module 'posthog-js' {
//   export interface PostHogEventSchemas {
//     'downloaded_file': { file_size_b: number; file_name?: string; file_type?: string }
//     'uploaded_file': { file_size_b: number; file_name?: string; file_type?: string }
//   }
// }
//
// And then re-exports posthog-js so you get typed events automatically!

// ============ ✅ CORRECT USAGE ============

// Required property with optional properties
posthog.typed.downloaded_file({
    file_size_b: 1024000,
    file_name: 'report.pdf',
    file_type: 'application/pdf',
})

// Required property only
posthog.typed.uploaded_file({
    file_size_b: 524288,
})

// With additional custom properties (allowed)
posthog.typed.uploaded_file({
    file_size_b: 524288,
    file_name: 'data.csv',
    file_type: 'text/csv',
    upload_source: 'drag_and_drop', // Extra properties are allowed
    user_action: 'manual',
})

// ============ ❌ TYPE ERRORS ============

// Missing required property 'file_size_b'
posthog.typed.downloaded_file({
    file_name: 'report.pdf',
    file_type: 'application/pdf',
})

// Wrong type for 'file_size_b' (should be number, not string)
posthog.typed.downloaded_file({
    file_size_b: '1024000', // ❌ Error: Type 'string' is not assignable to type 'number'
    file_name: 'report.pdf',
})

// Wrong type for optional property
posthog.typed.uploaded_file({
    file_size_b: 524288,
    file_name: 12345, // ❌ Error: Type 'number' is not assignable to type 'string'
})

// ============ BACKWARD COMPATIBILITY ============

// You can still use the regular capture() for any event
posthog.capture('custom_event', {
    any_property: 'any_value',
})

/**
 * Architecture:
 *
 * 1. PostHog repo defines event schemas (via backend database)
 * 2. `posthog schema pull` generates posthog-typed.ts with:
 *    - Type augmentations (PostHogEventSchemas interface)
 *    - Re-export of posthog-js with types included
 * 3. posthog-js provides the generic .typed infrastructure using mapped types
 * 4. TypeScript infers specific methods (downloaded_file, uploaded_file, etc.) from your schemas
 *
 * The magic: Event-specific methods are NOT hardcoded in posthog-js!
 * They're generated dynamically by TypeScript from YOUR schema definitions.
 *
 * Benefits:
 * - ONE import - no boilerplate, no separate type imports
 * - Catch errors at compile time, not runtime
 * - Auto-completion for event methods and properties in your IDE
 * - Required fields are enforced, optional fields are optional
 * - Documentation of expected event structure lives with your code
 * - Refactoring safety when changing event schemas
 * - Clean API: posthog.typed.downloaded_file() vs posthog.capture('downloaded_file')
 */
