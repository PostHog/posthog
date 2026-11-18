import { randomUUID } from "node:crypto";

export type NextEventId = () => string;

/**
 * Per-process source of task run event ids: a random boot prefix plus a
 * monotonic counter. Ids are unique across agent restarts within a run and
 * ordered within one boot, so the same id can key an event in both the Redis
 * stream and the S3 run log.
 */
export function createEventIdSource(): NextEventId {
  const bootId = randomUUID().slice(0, 8);
  let seq = 0;
  return () => {
    seq += 1;
    return `${bootId}-${seq}`;
  };
}
