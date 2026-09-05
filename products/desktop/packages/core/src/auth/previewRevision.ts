import { injectable } from "inversify";

/**
 * Verdict of a preview deployment revision check.
 *
 * - `match`: the backend serves the revision this build was made for.
 * - `stale`: the backend moved (a push replaced the box behind the stable
 *   URL); the installed installer is an older revision and must not keep
 *   testing as if it were current. The user downloads a fresh artifact.
 * - `waking`: the backend is hibernated and serving its wake interstitial.
 *   Retryable with a bounded wait; safe reads may proceed, mutations must not
 *   be replayed automatically.
 * - `unknown`: the document could not be read or parsed. No claim either way.
 */
export type PreviewRevisionVerdict =
  | { status: "match" }
  | { status: "stale"; servedCommitSha: string }
  | { status: "waking" }
  | { status: "unknown"; reason: string };

export interface PreviewRevisionCheckInput {
  /** Base URL of the preview backend (the validated manifest origin). */
  backendOrigin: string;
  /** The commit SHA this installer was built from. */
  expectedCommitSha: string;
  /** The path the metadata document is served at. */
  metadataPath: string;
  /** Fetch implementation, injectable for tests. */
  fetchImpl: typeof fetch;
  /** Bounded timeout for the document request. */
  timeoutMs: number;
}

/**
 * Compare the revision the preview backend serves against the one this
 * installer was built from. Pure logic over an injected fetch, so the
 * verdict rules are unit-testable without a backend.
 *
 * A 200 whose body is the SPA (an uncached route serving the app shell
 * instead of the document) is a failure, not a match: only the exact
 * schema-validated JSON counts.
 */
@injectable()
export class PreviewRevisionChecker {
  async check(
    input: PreviewRevisionCheckInput,
  ): Promise<PreviewRevisionVerdict> {
    const url = `${input.backendOrigin}${input.metadataPath}`;
    let response: Response;
    try {
      response = await input.fetchImpl(url, {
        signal: AbortSignal.timeout(input.timeoutMs),
        // The document must never come from a stale cache entry: a replaced
        // backend would then read as the previous revision.
        cache: "no-store",
      });
    } catch (error) {
      return {
        status: "unknown",
        reason: error instanceof Error ? error.message : String(error),
      };
    }

    if (response.status === 503) {
      // The pen's edge serves a retry-503 while the hibernated box wakes.
      return { status: "waking" };
    }

    if (!response.ok) {
      return {
        status: "unknown",
        reason: `metadata returned HTTP ${response.status}`,
      };
    }

    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch (error) {
      return {
        status: "unknown",
        reason: `metadata is not JSON: ${error instanceof Error ? error.message : String(error)}`,
      };
    }

    const doc = parsed as {
      schemaVersion?: unknown;
      prNumber?: unknown;
      commitSha?: unknown;
      deploymentGeneration?: unknown;
    };
    if (
      typeof doc.schemaVersion !== "number" ||
      typeof doc.commitSha !== "string" ||
      !/^[0-9a-f]{40}$/.test(doc.commitSha)
    ) {
      // A 200 carrying the SPA (route fallback) or a truncated body parses as
      // an object but fails this shape check.
      return {
        status: "unknown",
        reason: "metadata document has an unexpected shape",
      };
    }

    if (doc.commitSha === input.expectedCommitSha) {
      return { status: "match" };
    }
    return { status: "stale", servedCommitSha: doc.commitSha };
  }
}
