import * as fs from "node:fs/promises";
import * as path from "node:path";
import { PostHogDetector } from "./detector.js";
import { EXT_TO_LANG_ID } from "./languages.js";
import { warn } from "./log.js";
import { ParseResult } from "./parse-result.js";
import type {
  DetectionConfig,
  ImportEdge,
  LocalWrapper,
  ParseContext,
} from "./types.js";

const MAX_WRAPPER_SOURCE_BYTES = 1_000_000;
const WRAPPER_CACHE_MAX = 1024;
const POSTHOG_LITERAL_REGEX = /posthog/i;

interface WrapperCacheEntry {
  mtimeMs: number;
  wrappers: LocalWrapper[];
}

export class PostHogEnricher {
  private detector = new PostHogDetector();
  private wrapperCache = new Map<string, WrapperCacheEntry>();

  updateConfig(config: DetectionConfig): void {
    this.detector.updateConfig(config);
    this.wrapperCache.clear();
  }

  isSupported(langId: string): boolean {
    return this.detector.isSupported(langId);
  }

  get supportedLanguages(): string[] {
    return this.detector.supportedLanguages;
  }

  async parse(
    source: string,
    languageId: string,
    context?: ParseContext,
  ): Promise<ParseResult> {
    const results = await Promise.allSettled([
      this.detector.findPostHogCalls(source, languageId, context),
      this.detector.findInitCalls(source, languageId),
      this.detector.findFlagAssignments(source, languageId),
      this.detector.findVariantBranches(source, languageId),
      this.detector.findFunctions(source, languageId),
    ]);

    const settled = results.map((r, i) => {
      if (r.status === "fulfilled") {
        return r.value;
      }
      const labels = [
        "calls",
        "initCalls",
        "flagAssignments",
        "variantBranches",
        "functions",
      ];
      warn(`enricher: ${labels[i]} detection failed`, r.reason);
      return [];
    });

    return new ParseResult(
      source,
      languageId,
      settled[0] as Awaited<ReturnType<PostHogDetector["findPostHogCalls"]>>,
      settled[1] as Awaited<ReturnType<PostHogDetector["findInitCalls"]>>,
      settled[2] as Awaited<ReturnType<PostHogDetector["findFlagAssignments"]>>,
      settled[3] as Awaited<ReturnType<PostHogDetector["findVariantBranches"]>>,
      settled[4] as Awaited<ReturnType<PostHogDetector["findFunctions"]>>,
    );
  }

  /**
   * Detect wrapper functions (functions that internally call a PostHog SDK
   * method) defined in the given source. Used by callers like `enrichSource`
   * to pick up same-file wrappers such as `track(...)` without threading
   * through filesystem I/O.
   */
  async findWrappersInSource(
    source: string,
    languageId: string,
  ): Promise<LocalWrapper[]> {
    return this.detector.findWrappers(source, languageId);
  }

  async parseFile(filePath: string): Promise<ParseResult> {
    const ext = path.extname(filePath).toLowerCase();
    const languageId = EXT_TO_LANG_ID[ext];
    if (!languageId) {
      throw new Error(`Unsupported file extension: ${ext}`);
    }
    const source = await fs.readFile(filePath, "utf-8");
    return this.parse(source, languageId);
  }

  /**
   * Parse a file for wrapper definitions (functions that directly call PostHog SDK methods).
   * Results are cached per absolute path + mtime so subsequent calls within the same session
   * are cheap. Returns [] for unsupported extensions, unreadable files, or files larger than
   * `MAX_WRAPPER_SOURCE_BYTES`.
   */
  async getWrappersForFile(absPath: string): Promise<LocalWrapper[]> {
    const ext = path.extname(absPath).toLowerCase();
    const languageId = EXT_TO_LANG_ID[ext];
    if (!languageId || !this.isSupported(languageId)) {
      return this.setWrapperCache(absPath, 0, []);
    }

    let mtimeMs = 0;
    try {
      const stat = await fs.stat(absPath);
      mtimeMs = stat.mtimeMs;
      if (stat.size > MAX_WRAPPER_SOURCE_BYTES) {
        return this.setWrapperCache(absPath, mtimeMs, []);
      }
    } catch {
      return this.setWrapperCache(absPath, 0, []);
    }

    const cached = this.wrapperCache.get(absPath);
    if (cached && cached.mtimeMs === mtimeMs) {
      this.touchCache(absPath);
      return cached.wrappers;
    }

    let source: string;
    try {
      source = await fs.readFile(absPath, "utf-8");
    } catch {
      return this.setWrapperCache(absPath, mtimeMs, []);
    }

    // Cheap text-level guard: wrapper source must reference posthog/PostHog.
    if (!POSTHOG_LITERAL_REGEX.test(source)) {
      return this.setWrapperCache(absPath, mtimeMs, []);
    }

    const wrappers = await this.detector.findWrappers(source, languageId);
    return this.setWrapperCache(absPath, mtimeMs, wrappers);
  }

  async findImportsInSource(
    source: string,
    languageId: string,
    callerAbsPath: string,
  ): Promise<ImportEdge[]> {
    return this.detector.findImports(source, languageId, callerAbsPath);
  }

  clearWrapperCache(): void {
    this.wrapperCache.clear();
  }

  dispose(): void {
    this.detector.dispose();
    this.wrapperCache.clear();
  }

  private setWrapperCache(
    absPath: string,
    mtimeMs: number,
    wrappers: LocalWrapper[],
  ): LocalWrapper[] {
    if (this.wrapperCache.size >= WRAPPER_CACHE_MAX) {
      const oldest = this.wrapperCache.keys().next().value;
      if (oldest !== undefined) {
        this.wrapperCache.delete(oldest);
      }
    }
    this.wrapperCache.set(absPath, { mtimeMs, wrappers });
    return wrappers;
  }

  private touchCache(absPath: string): void {
    const entry = this.wrapperCache.get(absPath);
    if (!entry) return;
    this.wrapperCache.delete(absPath);
    this.wrapperCache.set(absPath, entry);
  }
}
