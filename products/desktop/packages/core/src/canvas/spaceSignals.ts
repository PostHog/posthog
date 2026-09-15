import { type ContextObject, parsePostHogObjectUrl } from "./contextDocument";

/** One raw finding a scout or source product filed about an object this space watches. */
export interface SpaceSignal {
  content: string;
  sourceProduct: string;
  sourceType: string;
  sourceId: string;
  timestamp: string;
}

const MIN_TITLE_LENGTH = 6;
const WINDOW_DAYS = 7;
export const SPACE_SIGNALS_LIMIT = 8;

function sqlString(value: string): string {
  return `'${value.replace(/\\/g, "\\\\").replace(/'/g, "''")}'`;
}

/**
 * HogQL for the latest signals about the objects a space watches. Signals live
 * in the `document_embeddings` table; the object they are about sits in the
 * metadata `source_id`, so a watched flag, experiment, insight, or error issue
 * matches on its id, and a long enough title matches in the signal text as a
 * fallback. Returns null when the space watches nothing that can match.
 */
export function buildSpaceSignalsQuery(
  objects: ContextObject[],
): string | null {
  const ids = new Set<string>();
  const titles = new Set<string>();
  for (const object of objects) {
    const parsed = parsePostHogObjectUrl(object.url);
    if (parsed && parsed.kind !== "link") ids.add(parsed.id);
    const title = object.title.trim();
    if (title.length >= MIN_TITLE_LENGTH) titles.add(title);
  }
  if (ids.size === 0 && titles.size === 0) return null;

  const clauses: string[] = [];
  if (ids.size > 0) {
    clauses.push(
      `metadata.source_id IN (${[...ids].map(sqlString).join(", ")})`,
    );
  }
  for (const title of titles) {
    clauses.push(`content ILIKE ${sqlString(`%${title}%`)}`);
  }

  return `SELECT content, source_product, source_type, source_id, signal_ts
FROM (
  SELECT
    document_id,
    argMax(content, inserted_at) AS content,
    argMax(metadata.source_product, inserted_at) AS source_product,
    argMax(metadata.source_type, inserted_at) AS source_type,
    argMax(metadata.source_id, inserted_at) AS source_id,
    argMax(metadata.deleted, inserted_at) AS deleted,
    argMax(timestamp, inserted_at) AS signal_ts
  FROM document_embeddings
  WHERE product = 'signals'
    AND document_type = 'signal'
    AND timestamp >= now() - INTERVAL ${WINDOW_DAYS} DAY
    AND (${clauses.join(" OR ")})
  GROUP BY document_id
)
WHERE deleted != 'true'
ORDER BY signal_ts DESC
LIMIT ${SPACE_SIGNALS_LIMIT}`;
}

export function parseSpaceSignalRows(rows: unknown[][]): SpaceSignal[] {
  const signals: SpaceSignal[] = [];
  for (const row of rows) {
    const [content, sourceProduct, sourceType, sourceId, timestamp] = row;
    if (typeof content !== "string" || !content.trim()) continue;
    signals.push({
      content: content.trim(),
      sourceProduct: typeof sourceProduct === "string" ? sourceProduct : "",
      sourceType: typeof sourceType === "string" ? sourceType : "",
      sourceId: typeof sourceId === "string" ? sourceId : "",
      timestamp: typeof timestamp === "string" ? timestamp : "",
    });
  }
  return signals;
}
