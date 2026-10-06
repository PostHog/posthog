/**
 * Byte budget for one append_log request body. The server rejects a body
 * above 20 MB (Django's DATA_UPLOAD_MAX_MEMORY_SIZE) with a 400 that is not
 * retryable, so a larger batch is lost.
 */
export const MAX_LOG_BATCH_BYTES = 4 * 1024 * 1024;

export interface LogBatch<T> {
  entries: T[];
  bytes: number;
}

/**
 * Splits entries, in order, into batches whose serialized size stays under
 * `maxBytes`. An entry that is larger than `maxBytes` gets a batch of its
 * own, so it can only fail by itself.
 */
export function splitLogBatches<T>(
  entries: T[],
  maxBytes: number = MAX_LOG_BATCH_BYTES,
): LogBatch<T>[] {
  const batches: LogBatch<T>[] = [];
  let current: LogBatch<T> = { entries: [], bytes: 0 };
  for (const entry of entries) {
    // +1 for the comma that separates array items.
    const size = Buffer.byteLength(JSON.stringify(entry)) + 1;
    if (current.entries.length > 0 && current.bytes + size > maxBytes) {
      batches.push(current);
      current = { entries: [], bytes: 0 };
    }
    current.entries.push(entry);
    current.bytes += size;
  }
  if (current.entries.length > 0) {
    batches.push(current);
  }
  return batches;
}
