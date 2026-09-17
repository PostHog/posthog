import { type ContextObject, parsePostHogObjectUrl } from "./contextDocument";

export interface SpaceSignal {
  content: string;
  sourceProduct: string;
  sourceType: string;
  sourceId: string;
  timestamp: string;
  url: string | null;
}

const MIN_TITLE_LENGTH = 6;
const WINDOW_DAYS = 7;
export const SPACE_SIGNALS_LIMIT = 8;

const SIGNAL_MODEL = "text-embedding-3-small-1536";

function sqlString(value: string): string {
  return `'${value.replace(/\\/g, "\\\\").replace(/'/g, "''")}'`;
}

function sqlList(values: Iterable<string>): string {
  return [...values].map(sqlString).join(", ");
}

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

function text(cell: unknown): string {
  return typeof cell === "string" ? cell : "";
}

export function parseSpaceSignalRows(rows: unknown[][]): SpaceSignal[] {
  return rows.flatMap((row) => {
    const [content, sourceProduct, sourceType, sourceId, timestamp, url] = row;
    if (!text(content).trim()) return [];
    return [
      {
        content: text(content).trim(),
        sourceProduct: text(sourceProduct),
        sourceType: text(sourceType),
        sourceId: text(sourceId),
        timestamp: text(timestamp),
        url: text(url) || null,
      },
    ];
  });
}
