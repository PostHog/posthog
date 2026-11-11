import * as path from "node:path";
import type { PostHogAPIConfig } from "@posthog/agent-contracts";
import { enrichSource, PostHogEnricher } from "@posthog/enricher";

export interface FileEnrichmentDeps {
  enricher: PostHogEnricher;
  apiConfig: PostHogAPIConfig;
}

export interface Enrichment {
  deps: FileEnrichmentDeps;
  dispose(): void;
}

export function createEnrichment(
  apiConfig: PostHogAPIConfig | undefined,
): Enrichment | undefined {
  if (!apiConfig) return undefined;
  const enricher = new PostHogEnricher();
  return {
    deps: { enricher, apiConfig },
    dispose: () => enricher.dispose(),
  };
}

export async function enrichFileForAgent(
  deps: FileEnrichmentDeps,
  filePath: string,
  content: string,
): Promise<string | null> {
  try {
    const apiKey = await deps.apiConfig.getApiKey();
    if (!apiKey) return null;

    const enriched = await enrichSource({
      enricher: deps.enricher,
      apiConfig: {
        apiKey,
        host: deps.apiConfig.apiUrl,
        publicHost: deps.apiConfig.publicApiUrl,
        projectId: deps.apiConfig.projectId,
      },
      filePath,
      absolutePath: path.resolve(filePath),
      content,
    });
    if (!enriched) return null;

    const annotated = enriched.toInlineComments({
      includeEventDescriptions: false,
      includeExperimentNames: false,
    });
    return annotated === content ? null : annotated;
  } catch {
    return null;
  }
}
