import { type ContextObject, parsePostHogObjectUrl } from "./contextDocument";

/** One raw finding a scout or source product filed about an object this space watches. */
export interface SpaceSignal {
  content: string;
  sourceProduct: string;
  sourceType: string;
  sourceId: string;
  timestamp: string;
  /** Where the source product points for this signal, when it gave one. */
  url: string | null;
}

const MIN_TITLE_LENGTH = 6;
const WINDOW_DAYS = 7;
export const SPACE_SIGNALS_LIMIT = 8;

// Signals are embedding documents; the lazy `document_embeddings` table routes
// on this filter, and every signals query in the backend uses the same model.
const SIGNAL_MODEL = "text-embedding-3-small-1536";

function sqlString(value: string): string {
  return `'${value.replace(/\\/g, "\\\\").replace(/'/g, "''")}'`;
}

function sqlList(values: Iterable<string>): string {
  return [...values].map(sqlString).join(", ");
}

/**
 * HogQL for the latest signals about the objects a space watches. A signal
 * names its object in `metadata.source_id` (error issues, replay scanners),
 * in `metadata.extra` (an analytics anomaly carries its insight, scout evidence
 * carries the URLs it read), or only in its text. Each watched object matches
 * on all three: its id, its app path anywhere in the metadata, and its title in
 * the content. Returns null when the space watches nothing that can match.
 */
export function buildSpaceSignalsQuery(
  objects: ContextObject[],
): string | null {
  const ids = new Set<string>();
  const insightIds = new Set<string>();
  const paths = new Set<string>();
  const titles = new Set<string>();
  for (const object of objects) {
    const parsed = parsePostHogObjectUrl(object.url);
    if (parsed && parsed.kind !== "link") {
      ids.add(parsed.id);
      paths.add(parsed.path);
      if (parsed.kind === "insight") insightIds.add(parsed.id);
    }
    const title = object.title.trim();
    if (title.length >= MIN_TITLE_LENGTH) titles.add(title);
  }
  if (ids.size === 0 && titles.size === 0) return null;

  const clauses: string[] = [];
  if (ids.size > 0) {
    clauses.push(
      `JSONExtractString(metadata, 'source_id') IN (${sqlList(ids)})`,
    );
  }
  if (insightIds.size > 0) {
    clauses.push(
      `JSONExtractString(metadata, 'extra', 'insight_short_id') IN (${sqlList(insightIds)})`,
      `JSONExtractString(metadata, 'extra', 'insight_id') IN (${sqlList(insightIds)})`,
    );
  }
  for (const path of paths) {
    clauses.push(`metadata ILIKE ${sqlString(`%${path}%`)}`);
  }
  for (const title of titles) {
    clauses.push(`content ILIKE ${sqlString(`%${title}%`)}`);
  }

  return `SELECT signal_content, source_product, source_type, source_id, signal_ts, url
FROM (
  SELECT
    document_id,
    argMax(content, inserted_at) AS signal_content,
    argMax(JSONExtractString(metadata, 'source_product'), inserted_at) AS source_product,
    argMax(JSONExtractString(metadata, 'source_type'), inserted_at) AS source_type,
    argMax(JSONExtractString(metadata, 'source_id'), inserted_at) AS source_id,
    argMax(JSONExtractBool(metadata, 'deleted'), inserted_at) AS deleted,
    argMax(timestamp, inserted_at) AS signal_ts,
    argMax(
      coalesce(
        nullIf(JSONExtractString(metadata, 'extra', 'url'), ''),
        nullIf(JSONExtractString(metadata, 'extra', 'html_url'), ''),
        nullIf(JSONExtractString(metadata, 'extra', 'link'), ''),
        ''
      ),
      inserted_at
    ) AS url
  FROM document_embeddings
  WHERE model_name = ${sqlString(SIGNAL_MODEL)}
    AND product = 'signals'
    AND document_type = 'signal'
    AND timestamp >= now() - INTERVAL ${WINDOW_DAYS} DAY
    AND (${clauses.join("\n      OR ")})
  GROUP BY document_id
)
WHERE NOT deleted
ORDER BY signal_ts DESC
LIMIT ${SPACE_SIGNALS_LIMIT}`;
}

export function parseSpaceSignalRows(rows: unknown[][]): SpaceSignal[] {
  const signals: SpaceSignal[] = [];
  for (const row of rows) {
    const [content, sourceProduct, sourceType, sourceId, timestamp, url] = row;
    if (typeof content !== "string" || !content.trim()) continue;
    signals.push({
      content: content.trim(),
      sourceProduct: typeof sourceProduct === "string" ? sourceProduct : "",
      sourceType: typeof sourceType === "string" ? sourceType : "",
      sourceId: typeof sourceId === "string" ? sourceId : "",
      timestamp: typeof timestamp === "string" ? timestamp : "",
      url: typeof url === "string" && url ? url : null,
    });
  }
  return signals;
}
