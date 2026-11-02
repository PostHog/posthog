/**
 * Kafka header names that a producer and a consumer in different trees have to agree on.
 *
 * A consumer that reads one of these falls back to the message body when the header is absent, so a
 * name that drifts costs performance and never correctness. Nothing fails, which is why the name is
 * a shared constant rather than a literal on each side.
 */

/** The event's team, so a consumer can route or skip a message without parsing the body. */
export const TEAM_ID_HEADER = 'team_id'
