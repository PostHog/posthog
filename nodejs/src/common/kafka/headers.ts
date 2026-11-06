/**
 * Kafka header names that a producer and a consumer in different trees have to agree on.
 *
 * The name is a shared constant rather than a literal on each side because a drifted name fails
 * open: the consumer finds no header and falls back to the message body, so it costs performance
 * and nothing reports it. A drifted name is not the same as a wrong value, which each header
 * documents below.
 */

/**
 * The event's team, so a consumer can route or skip a message without parsing the body.
 *
 * A producer must take this from the same `team_id` it writes into the body. A missing header is
 * safe, because a consumer falls back to the body, but a wrong one is not: a consumer may skip the
 * message on the header alone, and the team the body names would then never see its event.
 */
export const TEAM_ID_HEADER = 'team_id'

/**
 * The event's name, so a consumer can skip an event no destination or workflow of its team admits
 * without parsing the body.
 *
 * The same rule as the team id applies: a producer takes it from the `event` it writes into the
 * body. A missing header is safe, a wrong one makes a consumer skip an event a destination wanted.
 */
export const EVENT_NAME_HEADER = 'event'
