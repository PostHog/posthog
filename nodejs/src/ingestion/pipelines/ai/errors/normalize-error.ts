/**
 * Error normalization for AI events.
 *
 * This module normalizes error messages by replacing dynamic values (IDs, timestamps, etc.)
 * with placeholders. This allows grouping of related errors that differ only in dynamic values.
 *
 * The normalization pipeline applies 15 regex replacements in order from most specific
 * to least specific to prevent pattern interference.
 */

// Truncate very long error messages to avoid storage bloat
// Most useful error info is at the beginning anyway
const MAX_ERROR_LENGTH = 1000

// Step 1: UUIDs and request IDs (e.g., req_abc123, 550e8400-e29b-41d4-a716-446655440000)
const UUID_AND_REQ_ID_PATTERN = /(req_[a-zA-Z0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/gi

// Step 2: ISO timestamps (e.g., 2025-11-08T14:25:51.767Z)
const ISO_TIMESTAMP_PATTERN = /[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]+Z?/g

// Step 3: Cloud resource paths (e.g., projects/123/locations/us-west2/publishers/google/models/gemini-pro)
const CLOUD_PATH_PATTERN = /projects\/[0-9a-z-]+(\/[a-z]+\/[0-9a-z-]+)+/gi

// Step 4: ResponseId JSON fields (e.g., "responseId":"h2sPacmZI4OWvPEPvIS16Ac")
const RESPONSE_ID_PATTERN = /"responseId":"[a-zA-Z0-9_-]+"/g

// Step 5: Generic JSON "id" fields (e.g., "id": "oJf6eVw-z1gNr-99c2d11d156dff07")
const JSON_ID_PATTERN = /"id":\s*"[a-zA-Z0-9_-]+"/g

// Step 6a: Tool call IDs with attribute syntax (e.g., tool_call_id='toolu_01LCbNr67BxhgUH6gndPCELW')
const TOOL_CALL_ID_PATTERN = /tool_call_id=['"][a-zA-Z0-9_-]+['"]/g

// Step 6b: Standalone toolu_ IDs (e.g., toolu_01Bj5f7R5g9vhe7MkEyFT6Ty)
const TOOLU_ID_PATTERN = /toolu_[a-zA-Z0-9]+/g

// Step 7: Function call IDs (e.g., function call call_edLiisyOJybNZLouC6MCNxyC)
const FUNCTION_CALL_PATTERN = /function call call_[a-zA-Z0-9]+/g

// Step 8: User IDs (e.g., 'user_id': 'user_32yQoBNWxpvzxVJG0S0zxnnVSCJ')
// Uses capture group to preserve the prefix like "'user_id': '"
const USER_ID_PATTERN = /(user_id.{0,4})user_[a-zA-Z0-9]+/g

// Step 9: Memory object IDs / hex addresses (e.g., 0xfffced405130)
const OBJECT_ID_PATTERN = /0x[0-9a-fA-F]+/g

// Step 10: Generic id='xxx' patterns (case insensitive)
const GENERIC_ID_PATTERN = /id=['"][a-zA-Z0-9_-]+['"]/gi

// Step 11: Token counts (e.g., "tokenCount":7125 or "tokenCount": 7125)
const TOKEN_COUNT_PATTERN = /"tokenCount":\s*[0-9]+/g

// Step 12: Large numeric IDs (9+ digits, e.g., project IDs like 1234567890)
const LARGE_NUMERIC_ID_PATTERN = /[0-9]{9,}/g

// Step 13: All remaining numbers
const ALL_NUMBERS_PATTERN = /[0-9]+/g

// Step 14: Multiple whitespace
const WHITESPACE_PATTERN = /\s+/g

/**
 * Normalize an error message by replacing dynamic values with placeholders.
 *
 * Replacements are applied in order from most specific to least specific:
 * 1. UUIDs and request IDs -> <ID>
 * 2. ISO timestamps -> <TIMESTAMP>
 * 3. Cloud paths -> projects/<PATH>
 * 4. Response IDs -> "responseId":"<RESPONSE_ID>"
 * 5. JSON "id" fields -> "id": "<ID>"
 * 6. Tool call IDs -> tool_call_id='<TOOL_CALL_ID>' and <TOOL_ID>
 * 7. Function call IDs -> function call call_<CALL_ID>
 * 8. User IDs -> user_<USER_ID>
 * 9. Object IDs (hex) -> <OBJECT_ID>
 * 10. Generic id='xxx' -> id='<ID>'
 * 11. Token counts -> "tokenCount":<TOKEN_COUNT>
 * 12. Large numeric IDs (9+ digits) -> <ID>
 * 13. All remaining numbers -> <N>
 * 14. Collapse whitespace
 * 15. Trim
 */
export function normalizeError(rawError: string): string {
    if (!rawError) {
        return ''
    }

    // Truncate before processing to avoid wasting CPU on text that will be discarded
    let normalized = rawError.length > MAX_ERROR_LENGTH ? rawError.slice(0, MAX_ERROR_LENGTH) + '...' : rawError

    // Apply steps in order (most specific to least specific)
    normalized = normalized.replace(UUID_AND_REQ_ID_PATTERN, '<ID>')
    normalized = normalized.replace(ISO_TIMESTAMP_PATTERN, '<TIMESTAMP>')
    normalized = normalized.replace(CLOUD_PATH_PATTERN, 'projects/<PATH>')
    normalized = normalized.replace(RESPONSE_ID_PATTERN, '"responseId":"<RESPONSE_ID>"')
    normalized = normalized.replace(JSON_ID_PATTERN, '"id": "<ID>"')
    normalized = normalized.replace(TOOL_CALL_ID_PATTERN, "tool_call_id='<TOOL_CALL_ID>'")
    normalized = normalized.replace(TOOLU_ID_PATTERN, '<TOOL_ID>')
    normalized = normalized.replace(FUNCTION_CALL_PATTERN, 'function call call_<CALL_ID>')
    normalized = normalized.replace(USER_ID_PATTERN, '$1user_<USER_ID>')
    normalized = normalized.replace(OBJECT_ID_PATTERN, '<OBJECT_ID>')
    normalized = normalized.replace(GENERIC_ID_PATTERN, "id='<ID>'")
    normalized = normalized.replace(TOKEN_COUNT_PATTERN, '"tokenCount":<TOKEN_COUNT>')
    normalized = normalized.replace(LARGE_NUMERIC_ID_PATTERN, '<ID>')
    normalized = normalized.replace(ALL_NUMBERS_PATTERN, '<N>')
    normalized = normalized.replace(WHITESPACE_PATTERN, ' ')

    return normalized.trim()
}
