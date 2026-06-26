import { validate as isValidUuid, version as uuidVersion } from 'uuid'

import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PipelineEvent } from '~/types'

/**
 * First-party PostHog libraries ($lib) that are known to still send non-UUIDv7
 * event ids, so they are exempt from the warning below. A library NOT on this
 * list that sends a non-v7 uuid is a new/unknown sender worth surfacing.
 *
 * Derived from the top non-v7 senders across the last 90 days of production
 * traffic (the `mat_$lib` materialized column). Most PostHog SDKs already mint a
 * time-ordered UUIDv7 client-side; the entries here are the SDKs still on UUIDv4
 * (migrations in flight: python/go/dotnet/ruby) plus older app builds pinned to
 * pre-v7 SDK versions, and the empty-$lib server-assigned path. Alongside the
 * first-party SDKs we list public, open-source third-party integrations seen in
 * the same data; private/customer-specific `$lib` names from the long tail are
 * intentionally left off (they would leak customer data in this public repo, and
 * tripping the warning for them is the desired signal).
 */
export const KNOWN_NON_V7_LIBS: ReadonlySet<string> = new Set<string>([
    // First-party PostHog SDKs and the server-assigned path.
    '', // server-assigned / no $lib reported
    'web',
    'posthog-node',
    'posthog-python',
    'posthog-go',
    'posthog-ios',
    'posthog-android',
    'posthog-ruby',
    'posthog-php',
    'posthog-dotnet',
    'posthog-rs',
    'posthog-react-native',
    'posthog-flutter',
    'posthog-edge',
    'posthog-java',
    'posthog-chrome-extension',
    'posthog-capture-v1-internal',
    // Public, open-source third-party integrations.
    'detsys-ids-client', // Determinate Systems' PostHog-compatible telemetry client
    'determinate-nixd', // Determinate Systems
    'pixiehog', // PixieHog: PostHog + Shopify connector app
    'github.com/hollow-cube/posthog-java', // community PostHog Java client
])

function isNonV7Uuid(uuid: string | null | undefined): boolean {
    // Only flag well-formed uuids whose version is not 7; a malformed/missing
    // uuid is a different failure mode and not this step's concern.
    return typeof uuid === 'string' && isValidUuid(uuid) && uuidVersion(uuid) !== 7
}

/**
 * Emits an ingestion warning when an event's uuid is not a UUIDv7 and the
 * sending library is not on the {@link KNOWN_NON_V7_LIBS} allowlist. UUIDv7
 * embeds the event time, which the backend relies on; this catches SDKs that
 * regress to (or never adopted) v7.
 */
export function createValidateEventUuidVersionStep<T extends { event: PipelineEvent }>(
    allowedLibs: ReadonlySet<string> = KNOWN_NON_V7_LIBS
): ProcessingStep<T, T> {
    return async function validateEventUuidVersionStep(input) {
        const { event } = input

        if (!isNonV7Uuid(event.uuid)) {
            return Promise.resolve(ok(input))
        }

        const rawLib = event.properties?.['$lib']
        const lib = typeof rawLib === 'string' ? rawLib : ''

        if (allowedLibs.has(lib)) {
            return Promise.resolve(ok(input))
        }

        const warnings: PipelineWarning[] = [
            {
                type: 'event_uuid_not_v7',
                details: {
                    eventUuid: event.uuid,
                    event: event.event,
                    distinctId: event.distinct_id,
                    lib,
                },
                // One warning per lib per team per hour, so each offending SDK is
                // surfaced independently rather than masking one another.
                key: lib,
            },
        ]

        return Promise.resolve(ok(input, [], warnings))
    }
}
