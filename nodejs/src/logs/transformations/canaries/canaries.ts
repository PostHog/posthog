/**
 * Production validation canaries for log transformations.
 *
 * These are NOT product templates and must never be offered to customers. They exist to
 * prove, against real production ingestion, that the log transformation pipeline does what
 * the unit tests claim it does — with a blast radius of zero for real log traffic.
 *
 * The safety contract every canary obeys:
 *
 *   1. A log transformation has NO filters — the API rejects them, so an enabled function
 *      runs against every single record for the team. Scoping therefore has to live in the
 *      Hog itself, and it has to be the very first thing the program does.
 *   2. Line 1 of every canary is the same guard: if the record's service_name is not the
 *      synthetic canary service, return it untouched. Real traffic pays one string compare
 *      and nothing else.
 *   3. Nothing here can drop, mutate, or annotate a record from a real service, even if the
 *      canary's own logic is wrong — a failing canary fails open, which leaves the record
 *      intact and stamps `$transformations_failed`.
 *
 * Records are selected into a specific test case with the `canary.case` log attribute, so a
 * single stream of canary logs exercises every case independently and the assertions do not
 * interfere with each other.
 */

export interface CanaryDefinition {
    /** Function name as it should be created in PostHog. */
    name: string
    description: string
    /** Lower runs first. Chaining assertions depend on this order. */
    execution_order: number
    hog: string
    inputs_schema: Record<string, unknown>[]
    inputs: Record<string, { value: unknown }>
}

/** The synthetic service every canary scopes itself to. No real service may use this name. */
export const CANARY_SERVICE = 'logs-transform-canary'

/**
 * Fake stand-in for a real secret. It is deliberately worthless: canary 4 tries to leak it
 * on purpose, so if redaction is broken we learn that from a harmless sentinel rather than
 * by writing a live credential into stored production logs.
 */
export const CANARY_FAKE_SECRET = 'canary-fake-secret-not-a-credential-7f3a91'

const serviceGuardInput = {
    key: 'canaryService',
    type: 'string',
    label: 'Canary service name',
    description:
        'Only records whose service_name equals this value are touched. Every other record is returned untouched.',
    required: true,
    default: CANARY_SERVICE,
}

/**
 * Proves: transformations execute at all; body, severity_text, attributes and
 * resource_attributes are writable; the read-only fields really are read-only.
 *
 * Also stamps the first half of the chain marker, and writes a numeric-looking string
 * attribute — see `canary.numeric` in the validation matrix, that one is a live question
 * about the attribute wire encoding rather than a settled expectation.
 */
const canary1: CanaryDefinition = {
    name: 'canary-1-mutate-and-readonly',
    description:
        'VALIDATION CANARY — no-op for every service except the synthetic canary service. Proves writable fields apply and read-only fields are ignored.',
    execution_order: 1,
    hog: `if (record.service_name != inputs.canaryService) {
    return record
}

let r := record

// Chain marker, first half. Letters, not digits: see canary.numeric below.
let chain := r.attributes['canary.chain']
if (chain == null) {
    chain := ''
}
r.attributes['canary.chain'] := concat(chain, 'a')
r.attributes['canary.t1'] := 'applied'
r.resource_attributes['canary.t1.resource'] := 'applied'

// A numeric-looking string. encodeLogAttributeValue leaves already-valid JSON alone, so
// this is stored bare as 1 rather than "1", and the sink's JSONExtractString may not
// return it. Asserted in prod, not assumed.
r.attributes['canary.numeric'] := '1'

if (r.attributes['canary.case'] == 'mutate') {
    if (r.body != null) {
        r.body := replaceAll(r.body, 'CANARY_REDACT_ME', '[REDACTED]')
    }
    r.severity_text := 'warn'

    // Read-only fields. Every assignment below must have no effect on the stored record.
    r.service_name := 'canary-hijacked'
    r.severity_number := 99
    r.timestamp := 0
    r.trace_id := '000102030405060708090a0b0c0d0e0f'
    r.event_name := 'canary-hijacked'
}

return r
`,
    inputs_schema: [serviceGuardInput],
    inputs: { canaryService: { value: CANARY_SERVICE } },
}

/**
 * Proves: returning null drops the record; execution order is respected (this appends to
 * the marker canary 1 wrote); a drop short-circuits the functions after it.
 */
const canary2: CanaryDefinition = {
    name: 'canary-2-drop-and-chain',
    description:
        'VALIDATION CANARY — no-op for every service except the synthetic canary service. Proves drop-on-null and execution ordering.',
    execution_order: 2,
    hog: `if (record.service_name != inputs.canaryService) {
    return record
}

let r := record

// Chain marker, second half. A stored value of 'ab' proves canary 1 ran first.
let chain := r.attributes['canary.chain']
if (chain == null) {
    chain := ''
}
r.attributes['canary.chain'] := concat(chain, 'b')

if (r.attributes['canary.case'] == 'drop') {
    return null
}

return r
`,
    inputs_schema: [serviceGuardInput],
    inputs: { canaryService: { value: CANARY_SERVICE } },
}

/**
 * Proves the property that actually protects production: fail-open. A transformation that
 * returns garbage, or that never terminates, must leave the record intact and let it
 * through — annotated, counted, and surfaced in the function's logs, but never lost.
 */
const canary3: CanaryDefinition = {
    name: 'canary-3-fail-open',
    description:
        'VALIDATION CANARY — no-op for every service except the synthetic canary service. Proves a failing or runaway transformation cannot drop or corrupt a record.',
    execution_order: 3,
    hog: `if (record.service_name != inputs.canaryService) {
    return record
}

let mode := record.attributes['canary.case']

if (mode == 'fail-invalid') {
    // Not a record object, so applyTransformResult reports 'invalid' and the outcome is
    // 'failed'. The record must survive completely untouched.
    return 'this-is-not-a-record'
}

if (mode == 'fail-timeout') {
    // Runaway loop. The per-record VM kill has to stop this and fail open.
    let i := 0
    while (true) {
        i := i + 1
    }
}

let r := record
r.attributes['canary.t3'] := 'reached'
return r
`,
    inputs_schema: [serviceGuardInput],
    inputs: { canaryService: { value: CANARY_SERVICE } },
}

/**
 * Proves: encrypted inputs are decrypted for the running function, and are scrubbed back
 * out of anything the function writes — stored fields and captured print() logs alike.
 * A failure here would write a secret into permanent log storage, so the value used is a
 * deliberately worthless sentinel.
 */
const canary4: CanaryDefinition = {
    name: 'canary-4-secret-redaction',
    description:
        'VALIDATION CANARY — no-op for every service except the synthetic canary service. Deliberately tries to leak an encrypted input; redaction must scrub it from the record and the logs.',
    execution_order: 4,
    hog: `if (record.service_name != inputs.canaryService) {
    return record
}

if (record.attributes['canary.case'] != 'leak') {
    return record
}

let r := record

// Deliberate leak attempt on all three surfaces an encrypted input could escape through.
print(concat('leak-in-print:', inputs.fakeSecret))
r.body := concat('leak-in-body:', inputs.fakeSecret)
r.attributes['canary.leak'] := inputs.fakeSecret

return r
`,
    inputs_schema: [
        serviceGuardInput,
        {
            key: 'fakeSecret',
            type: 'string',
            label: 'Fake secret',
            description:
                'A worthless sentinel, never a real credential. The canary tries to leak this on purpose so redaction can be observed.',
            required: true,
            secret: true,
            default: CANARY_FAKE_SECRET,
        },
    ],
    inputs: {
        canaryService: { value: CANARY_SERVICE },
        fakeSecret: { value: CANARY_FAKE_SECRET },
    },
}

/** In execution order. Enable one at a time — see the rollout steps in the PR description. */
export const CANARIES: CanaryDefinition[] = [canary1, canary2, canary3, canary4]
