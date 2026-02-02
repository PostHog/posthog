# Phase 1: Per-Trigger Sampling Evaluation Logic (Pseudocode)

## Overview
This describes how the posthog-js SDK would evaluate triggers with per-trigger sampling rates.

## Data Structures

```typescript
interface SessionRecordingRemoteConfig {
    sampleRate: string | null  // Global fallback (e.g., "0.10" for 10%)
    urlTriggers: UrlTrigger[]
    eventTriggers: EventTrigger[]
    linkedFlag: FlagConfig | null
    triggerMatchType: 'any' | 'all'
}

interface UrlTrigger {
    url: string
    matching: 'regex'
    sampleRate?: number  // Optional: 0-1
}

interface EventTrigger {
    event: string
    sampleRate?: number  // Optional: 0-1
}
```

## Evaluation Algorithm

### Option A: Sampling as Part of Trigger Match (Recommended)

Each trigger evaluates to true/false based on BOTH condition AND sampling.

```typescript
function shouldStartRecording(config: SessionRecordingRemoteConfig): boolean {
    const globalSampleRate = parseFloat(config.sampleRate || '1.0')

    // Evaluate each URL trigger
    const urlMatches = config.urlTriggers.map(trigger => {
        const conditionMatches = matchesUrlPattern(trigger.url, window.location.href)
        if (!conditionMatches) return false

        // If trigger specifies sample rate, use it; otherwise use global
        const effectiveSampleRate = trigger.sampleRate ?? globalSampleRate
        return passesSampling(effectiveSampleRate)
    })

    // Evaluate each event trigger (when event fires)
    const eventMatches = config.eventTriggers.map(trigger => {
        const conditionMatches = hasEventFired(trigger.event)
        if (!conditionMatches) return false

        const effectiveSampleRate = trigger.sampleRate ?? globalSampleRate
        return passesSampling(effectiveSampleRate)
    })

    // Evaluate linked flag
    const flagMatches = config.linkedFlag
        ? isFlagEnabled(config.linkedFlag)
        : false

    // Combine all matches based on matchType
    const allMatches = [...urlMatches, ...eventMatches]
    if (flagMatches) allMatches.push(flagMatches)

    if (config.triggerMatchType === 'all') {
        // ALL enabled triggers must match
        return allMatches.length > 0 && allMatches.every(m => m)
    } else {
        // ANY trigger matching is sufficient
        return allMatches.some(m => m)
    }
}

function passesSampling(sampleRate: number): boolean {
    // Use deterministic hash on distinct_id or session_id for consistency
    const userId = posthog.get_distinct_id()
    const hash = simpleHash(userId) % 100
    return hash < (sampleRate * 100)
}
```

### Option B: Collect All Sample Rates, Then Apply

Separate trigger evaluation from sampling decision.

```typescript
function shouldStartRecording(config: SessionRecordingRemoteConfig): {
    record: boolean
    reason: string
    sampleRate: number
} {
    const globalSampleRate = parseFloat(config.sampleRate || '1.0')
    const matchedTriggers: {type: string, sampleRate: number}[] = []

    // Check URL triggers
    for (const trigger of config.urlTriggers) {
        if (matchesUrlPattern(trigger.url, window.location.href)) {
            matchedTriggers.push({
                type: 'url',
                sampleRate: trigger.sampleRate ?? globalSampleRate
            })
        }
    }

    // Check event triggers (when events fire)
    for (const trigger of config.eventTriggers) {
        if (hasEventFired(trigger.event)) {
            matchedTriggers.push({
                type: 'event',
                sampleRate: trigger.sampleRate ?? globalSampleRate
            })
        }
    }

    // Check linked flag
    if (config.linkedFlag && isFlagEnabled(config.linkedFlag)) {
        matchedTriggers.push({
            type: 'flag',
            sampleRate: globalSampleRate  // Flags don't have per-trigger sampling in Phase 1
        })
    }

    // Apply matchType logic
    let shouldMatch = false
    if (config.triggerMatchType === 'all') {
        // For 'all': need at least one trigger, and all must match
        const totalTriggers = config.urlTriggers.length + config.eventTriggers.length + (config.linkedFlag ? 1 : 0)
        shouldMatch = totalTriggers > 0 && matchedTriggers.length === totalTriggers
    } else {
        // For 'any': at least one match
        shouldMatch = matchedTriggers.length > 0
    }

    if (!shouldMatch) {
        return { record: false, reason: 'no_triggers_matched', sampleRate: 0 }
    }

    // Determine final sample rate
    const finalSampleRate = determineFinalSampleRate(matchedTriggers, config.triggerMatchType)

    // Apply sampling
    const passedSampling = passesSampling(finalSampleRate)

    return {
        record: passedSampling,
        reason: passedSampling ? 'trigger_matched_and_sampled' : 'trigger_matched_but_not_sampled',
        sampleRate: finalSampleRate
    }
}

function determineFinalSampleRate(
    matchedTriggers: {type: string, sampleRate: number}[],
    matchType: 'any' | 'all'
): number {
    if (matchedTriggers.length === 0) return 0

    if (matchType === 'any') {
        // Use the HIGHEST sample rate among matched triggers
        // Rationale: Give the user the best chance of recording
        return Math.max(...matchedTriggers.map(t => t.sampleRate))
    } else {
        // matchType === 'all'
        // Use the LOWEST sample rate (most restrictive)
        // Rationale: All conditions must pass, including sampling
        return Math.min(...matchedTriggers.map(t => t.sampleRate))
    }
}
```

## Comparison: Option A vs Option B

### Option A: Sampling as Part of Match
**Pros:**
- Simpler logic
- Each trigger independently decides match + sampling
- Natural with 'any' matchType

**Cons:**
- With 'all' matchType, sampling happens per-trigger, which can be confusing
  - Example: URL matches (5% sample) AND event fires (50% sample) → effective rate is 0.05 * 0.50 = 2.5%
  - This multiplicative effect may not be intuitive to users

### Option B: Collect Matches, Then Sample
**Pros:**
- Clear separation: "Did triggers match?" then "Should we sample?"
- Easier to explain to users
- Can use highest/lowest sample rate strategy

**Cons:**
- Slightly more complex code
- Need to decide: highest, lowest, or average sample rate?

## Recommendation: Option B with "Highest Sample Rate Wins"

For matchType 'any':
- Use the HIGHEST sample rate among matched triggers
- Rationale: User wants to capture the most important flows
- Example: URL A (5%) OR URL B (100%) → if B matches, use 100%

For matchType 'all':
- Use the LOWEST sample rate (most restrictive)
- Rationale: All conditions must pass, including the strictest sampling
- Example: URL matches (20%) AND event fires (50%) → use 20%

## Examples

### Example 1: matchType = 'any'

Config:
```json
{
  "urlTriggers": [
    {"url": "/checkout", "sampleRate": 1.0},
    {"url": "/browse", "sampleRate": 0.05}
  ],
  "sampleRate": "0.10",
  "triggerMatchType": "any"
}
```

Scenarios:
- User on `/checkout` → URL trigger matches with 100% → record 100% of sessions
- User on `/browse` → URL trigger matches with 5% → record 5% of sessions
- User on `/account` → No trigger matches → no recording

### Example 2: matchType = 'all'

Config:
```json
{
  "urlTriggers": [
    {"url": "/checkout", "sampleRate": 0.50}
  ],
  "eventTriggers": [
    {"event": "payment_started", "sampleRate": 0.20}
  ],
  "sampleRate": "0.10",
  "triggerMatchType": "all"
}
```

Scenarios:
- User on `/checkout` but no event → triggers don't all match → no recording
- User on `/checkout` AND `payment_started` fires → both match → use min(0.50, 0.20) = 20% sampling
- User on `/other-page` → triggers don't all match → no recording

### Example 3: Backward Compatibility

Config (old format):
```json
{
  "urlTriggers": [
    {"url": "/checkout", "matching": "regex"}
  ],
  "sampleRate": "0.25",
  "triggerMatchType": "any"
}
```

Behavior:
- Trigger has no `sampleRate` field → uses global `sampleRate` of 0.25 (25%)
- Fully backward compatible with existing configs

## Edge Cases

### No triggers configured
- Falls back to global `sampleRate` (current behavior)
- If global rate is null/absent, defaults to 100%

### Trigger with sampleRate = 0
- 0% means "never record" when this trigger matches
- Can be used to explicitly exclude certain URLs

### Multiple triggers match with 'any'
- Use the highest sample rate among all matched triggers
- Ensures important flows get captured

### Linked flag + URL trigger with 'all'
- Linked flag uses global sample rate (no per-trigger rate for flags in Phase 1)
- URL trigger uses its specified rate
- Final rate = min(flagRate, urlRate)
