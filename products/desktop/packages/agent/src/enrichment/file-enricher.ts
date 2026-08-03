import * as path from "node:path";
import {
  EXT_TO_LANG_ID,
  type ImportEdge,
  type LocalWrapper,
  type ParseContext,
  PostHogEnricher,
} from "@posthog/enricher";
import type { PostHogAPIConfig } from "../types";
import type { Logger } from "../utils/logger";

export interface FileEnrichmentDeps {
  enricher: PostHogEnricher;
  apiConfig: PostHogAPIConfig;
  logger?: Logger;
}

export interface Enrichment {
  deps: FileEnrichmentDeps;
  dispose(): void;
}

export function createEnrichment(
  apiConfig: PostHogAPIConfig | undefined,
  logger?: Logger,
): Enrichment | undefined {
  if (!apiConfig) return undefined;
  const enricher = new PostHogEnricher();
  return {
    deps: { enricher, apiConfig, logger },
    dispose: () => enricher.dispose(),
  };
}

const MAX_ENRICHMENT_BYTES = 1_000_000;
const MAX_RELATIVE_IMPORTS = 64;
const RELATIVE_IMPORT_REGEX =
  /(?:^|\n)\s*(?:import\b[^\n]*['"]\.{1,2}\/|from\s+\.)/;
const POSTHOG_LITERAL_REGEX = /posthog/i;

export async function enrichFileForAgent(
  deps: FileEnrichmentDeps,
  filePath: string,
  content: string,
): Promise<string | null> {
  if (!content || content.length > MAX_ENRICHMENT_BYTES) return null;

  const ext = path.extname(filePath).toLowerCase();
  const langId = EXT_TO_LANG_ID[ext];
  if (!langId || !deps.enricher.isSupported(langId)) return null;

  const hasPostHogLiteral = POSTHOG_LITERAL_REGEX.test(content);
  const hasRelativeImport = RELATIVE_IMPORT_REGEX.test(content);
  let parseContext: ParseContext | undefined;

  // Build wrapper context whenever the file has relative imports — direct PostHog
  // usage and wrapper usage can coexist in the same file, so we don't skip this
  // just because `posthog` already appears literally.
  if (hasRelativeImport) {
    const absPath = path.resolve(filePath);
    const ctx = await buildWrapperContext(deps, content, langId, absPath);
    if (ctx) parseContext = ctx;
  }

  // Bail only when nothing at all could be enriched: no direct posthog literal
  // AND no resolvable wrappers.
  if (!hasPostHogLiteral && !parseContext) return null;

  try {
    const parsed = await deps.enricher.parse(content, langId, parseContext);
    if (parsed.calls.length === 0 && parsed.initCalls.length === 0) {
      return null;
    }

    const apiKey = await deps.apiConfig.getApiKey();
    if (!apiKey) return null;

    const enriched = await parsed.enrichFromApi({
      apiKey,
      host: deps.apiConfig.apiUrl,
      projectId: deps.apiConfig.projectId,
      timeoutMs: 5_000,
    });

    const annotated = enriched.toInlineComments();
    if (annotated === content) {
      deps.logger?.debug("File enrichment produced no changes", {
        filePath,
        calls: parsed.calls.length,
      });
      return null;
    }
    deps.logger?.debug("File enriched", {
      filePath,
      calls: parsed.calls.length,
      viaWrappers: parsed.calls.filter((c) => c.viaWrapper).length,
    });
    return annotated;
  } catch (err) {
    const detail =
      err instanceof Error
        ? { message: err.message, name: err.name, stack: err.stack }
        : { value: String(err) };
    deps.logger?.debug("File enrichment failed", { filePath, ...detail });
    return null;
  }
}

async function buildWrapperContext(
  deps: FileEnrichmentDeps,
  content: string,
  langId: string,
  absPath: string,
): Promise<ParseContext | null> {
  let edges: ImportEdge[];
  try {
    edges = await deps.enricher.findImportsInSource(content, langId, absPath);
  } catch (err) {
    deps.logger?.debug("Import resolution failed", {
      absPath,
      err: err instanceof Error ? err.message : String(err),
    });
    return null;
  }

  if (!edges.length) return null;
  const bounded = edges.slice(0, MAX_RELATIVE_IMPORTS);

  const wrappersByLocalName = new Map<string, LocalWrapper>();
  const namespaceWrappers = new Map<string, Map<string, LocalWrapper>>();

  const resolutions = await Promise.all(
    bounded.map(async (edge) => {
      if (!edge.resolvedAbsPath) return null;
      const wrappers = await deps.enricher.getWrappersForFile(
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

  if (!wrappersByLocalName.size && !namespaceWrappers.size) return null;

  return { wrappersByLocalName, namespaceWrappers };
}
