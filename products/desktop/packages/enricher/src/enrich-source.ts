import type { EnrichedResult } from "./enriched-result.js";
import type { PostHogEnricher } from "./enricher.js";
import { EXT_TO_LANG_ID } from "./languages.js";
import type { LocalWrapper, ParseContext } from "./types.js";

export interface EnrichSourceApiConfig {
  apiKey: string;
  host: string;
  projectId: number;
  /** Timeout in ms for each PostHog API request (default: 5000). */
  timeoutMs?: number;
}

export interface EnrichSourceOptions {
  enricher: PostHogEnricher;
  apiConfig: EnrichSourceApiConfig;
  filePath: string;
  /**
   * Absolute filesystem path of the file. When provided, enrichment will
   * resolve relative imports to pick up wrapper functions (e.g. a `track(…)`
   * helper that internally calls `posthog.capture`).
   */
  absolutePath?: string;
  content: string;
  /** Skip files larger than this. Default: 1,000,000 bytes. */
  maxBytes?: number;
  onDebug?: (message: string, data?: Record<string, unknown>) => void;
}

const DEFAULT_MAX_BYTES = 1_000_000;
const DEFAULT_TIMEOUT_MS = 5_000;
const MAX_RELATIVE_IMPORTS = 64;
const RELATIVE_IMPORT_REGEX =
  /(?:^|\n)\s*(?:import\b[^\n]*['"]\.{1,2}\/|from\s+\.)/;

function extOf(filePath: string): string {
  const idx = filePath.lastIndexOf(".");
  return idx === -1 ? "" : filePath.slice(idx).toLowerCase();
}

async function buildParseContext(
  enricher: PostHogEnricher,
  content: string,
  langId: string,
  absolutePath: string | undefined,
  onDebug?: (message: string, data?: Record<string, unknown>) => void,
): Promise<ParseContext | undefined> {
  const wrappersByLocalName = new Map<string, LocalWrapper>();
  const namespaceWrappers = new Map<string, Map<string, LocalWrapper>>();

  const localWrappers = await enricher.findWrappersInSource(content, langId);
  for (const w of localWrappers) {
    wrappersByLocalName.set(w.name, w);
  }

  if (absolutePath && RELATIVE_IMPORT_REGEX.test(content)) {
    try {
      const edges = await enricher.findImportsInSource(
        content,
        langId,
        absolutePath,
      );
      const bounded = edges.slice(0, MAX_RELATIVE_IMPORTS);

      const resolutions = await Promise.all(
        bounded.map(async (edge) => {
          if (!edge.resolvedAbsPath) return null;
          const wrappers = await enricher.getWrappersForFile(
            edge.resolvedAbsPath,
          );
          if (!wrappers.length) return null;
          return { edge, wrappers };
        }),
      );

      for (const entry of resolutions) {
        if (!entry) continue;
        const { edge, wrappers } = entry;

        if (edge.isNamespace) {
          const nsMap = new Map<string, LocalWrapper>();
          for (const w of wrappers) {
            if (w.isNamedExport || w.isDefaultExport) {
              nsMap.set(w.name, w);
            }
          }
          if (nsMap.size) namespaceWrappers.set(edge.localName, nsMap);
          continue;
        }

        if (edge.isDefault) {
          const target = wrappers.find((w) => w.isDefaultExport);
          if (target) wrappersByLocalName.set(edge.localName, target);
          continue;
        }

        const target = wrappers.find(
          (w) => w.name === edge.importedName && w.isNamedExport,
        );
        if (target) wrappersByLocalName.set(edge.localName, target);
      }
    } catch (err) {
      onDebug?.("enrichSource: import resolution failed", {
        absolutePath,
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  if (!wrappersByLocalName.size && !namespaceWrappers.size) return undefined;
  return { wrappersByLocalName, namespaceWrappers };
}

/**
 * Shared enrichment pipeline used by both the agent (which then renders
 * inline comments) and the renderer (which consumes a serialised form).
 *
 * Returns `null` when the file is too large, has no PostHog references,
 * is an unsupported language, or the API call fails.
 */
export async function enrichSource({
  enricher,
  apiConfig,
  filePath,
  absolutePath,
  content,
  maxBytes = DEFAULT_MAX_BYTES,
  onDebug,
}: EnrichSourceOptions): Promise<EnrichedResult | null> {
  if (!content || content.length > maxBytes) return null;

  const langId = EXT_TO_LANG_ID[extOf(filePath)];
  if (!langId || !enricher.isSupported(langId)) return null;

  const parseContext = await buildParseContext(
    enricher,
    content,
    langId,
    absolutePath,
    onDebug,
  );

  const hasPostHogLiteral = /posthog/i.test(content);
  if (!hasPostHogLiteral && !parseContext) return null;

  try {
    const parsed = await enricher.parse(content, langId, parseContext);
    if (parsed.calls.length === 0 && parsed.initCalls.length === 0) {
      return null;
    }

    const enriched = await parsed.enrichFromApi({
      apiKey: apiConfig.apiKey,
      host: apiConfig.host,
      projectId: apiConfig.projectId,
      timeoutMs: apiConfig.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    });

    onDebug?.("enrichSource: enriched", {
      filePath,
      flags: enriched.flags.length,
      events: enriched.events.length,
    });
    return enriched;
  } catch (err) {
    onDebug?.("enrichSource: failed", {
      filePath,
      message: err instanceof Error ? err.message : String(err),
    });
    return null;
  }
}
