/**
 * Browserbase regions for agentic tests — keep in sync with
 * `products/agentic_tests/backend/logic/browserbase.SUPPORTED_REGIONS`.
 */

export const AGENTIC_TEST_BROWSERBASE_REGION_CODES = [
    'us-west-2',
    'us-east-1',
    'eu-central-1',
    'ap-southeast-1',
] as const

export type AgenticTestBrowserbaseRegionCode = (typeof AGENTIC_TEST_BROWSERBASE_REGION_CODES)[number]

export const DEFAULT_AGENTIC_TEST_BROWSERBASE_REGION: AgenticTestBrowserbaseRegionCode = 'us-west-2'

const REGION_LABELS: Record<AgenticTestBrowserbaseRegionCode, string> = {
    'us-west-2': '🇺🇸 US West (Oregon)',
    'us-east-1': '🇺🇸 US East (Virginia)',
    'eu-central-1': '🇪🇺 EU Central (Frankfurt)',
    'ap-southeast-1': '🇸🇬 Asia Pacific (Singapore)',
}

export const AGENTIC_TEST_REGION_OPTIONS: { value: AgenticTestBrowserbaseRegionCode; label: string }[] =
    AGENTIC_TEST_BROWSERBASE_REGION_CODES.map((value) => ({
        value,
        label: REGION_LABELS[value],
    }))

const SUPPORTED_SET = new Set<string>(AGENTIC_TEST_BROWSERBASE_REGION_CODES)

export function isAgenticTestBrowserbaseRegionCode(r: string): r is AgenticTestBrowserbaseRegionCode {
    return SUPPORTED_SET.has(r)
}

/** Non-empty list of supported region codes; empty/invalid API payloads default to US West. */
export function normalizeAgenticTestRegionsFromApi(value: unknown): AgenticTestBrowserbaseRegionCode[] {
    const raw = Array.isArray(value)
        ? value.filter((r): r is string => typeof r === 'string' && SUPPORTED_SET.has(r))
        : []
    const unique = [...new Set(raw)] as AgenticTestBrowserbaseRegionCode[]
    if (unique.length === 0) {
        return [DEFAULT_AGENTIC_TEST_BROWSERBASE_REGION]
    }
    return unique
}
