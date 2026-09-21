import { existsSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import Parser from "web-tree-sitter";
import type { LangFamily } from "./languages.js";
import { LANG_FAMILIES } from "./languages.js";
import { warn } from "./log.js";
import type { DetectionConfig } from "./types.js";
import { DEFAULT_CONFIG } from "./types.js";

function resolveGrammarsDir(): string {
  const thisFile = fileURLToPath(import.meta.url);
  const dir = path.dirname(thisFile);
  const candidates = [
    path.join(dir, "..", "grammars"),
    path.join(dir, "grammars"),
    path.join(dir, "..", "..", "grammars"),
  ];
  return candidates.find((p) => existsSync(p)) ?? candidates[0];
}

export class ParserManager {
  private parser: Parser | null = null;
  private languages = new Map<string, Parser.Language>();
  private languageKeys = new WeakMap<Parser.Language, string>();
  private queryCache = new Map<string, Parser.Query>();
  private failedQueries = new Set<string>();
  private maxCacheSize = 256;
  private initPromise: Promise<void> | null = null;
  private wasmDir = resolveGrammarsDir();
  config: DetectionConfig = DEFAULT_CONFIG;

  updateConfig(config: DetectionConfig): void {
    this.config = config;
    this.queryCache.clear();
    this.failedQueries.clear();
  }

  private async ensureInitialized(): Promise<void> {
    if (!this.initPromise) {
      this.initPromise = this.doInit();
    }
    return this.initPromise;
  }

  private async doInit(): Promise<void> {
    try {
      await Parser.init({
        locateFile: (scriptName: string) => path.join(this.wasmDir, scriptName),
      });
      this.parser = new Parser();
    } catch (err) {
      this.initPromise = null;
      warn("Failed to initialize tree-sitter parser", err);
      throw err;
    }
  }

  isSupported(langId: string): boolean {
    return langId in LANG_FAMILIES;
  }

  get supportedLanguages(): string[] {
    return Object.keys(LANG_FAMILIES);
  }

  async ensureReady(
    langId: string,
  ): Promise<{ lang: Parser.Language; family: LangFamily } | null> {
    await this.ensureInitialized();
    if (!this.parser) {
      return null;
    }

    const family = LANG_FAMILIES[langId];
    if (!family) {
      return null;
    }

    let lang = this.languages.get(family.wasm);
    if (!lang) {
      try {
        const wasmPath = path.join(this.wasmDir, family.wasm);
        lang = await Parser.Language.load(wasmPath);
        this.languages.set(family.wasm, lang);
        this.languageKeys.set(lang, family.wasm);
      } catch (err) {
        warn(`Failed to load grammar ${family.wasm}`, err);
        return null;
      }
    }

    return { lang, family };
  }

  parse(text: string, lang: Parser.Language): Parser.Tree | null {
    if (!this.parser) {
      return null;
    }
    this.parser.setLanguage(lang);
    return this.parser.parse(text);
  }

  getQuery(lang: Parser.Language, queryStr: string): Parser.Query | null {
    if (!queryStr.trim()) {
      return null;
    }

    const langKey = this.languageKeys.get(lang) ?? lang.toString();
    const cacheKey = `${langKey}:${queryStr}`;

    if (this.failedQueries.has(cacheKey)) {
      return null;
    }

    let query = this.queryCache.get(cacheKey);
    if (query) {
      // LRU: move to end by deleting and re-inserting
      this.queryCache.delete(cacheKey);
      this.queryCache.set(cacheKey, query);
      return query;
    }

    try {
      query = lang.query(queryStr);
      // Evict oldest entry if at capacity
      if (this.queryCache.size >= this.maxCacheSize) {
        const oldest = this.queryCache.keys().next().value;
        if (oldest !== undefined) {
          this.queryCache.delete(oldest);
        }
      }
      this.queryCache.set(cacheKey, query);
      return query;
    } catch {
      this.failedQueries.add(cacheKey);
      return null;
    }
  }

  dispose(): void {
    this.parser?.delete();
    this.parser = null;
    this.initPromise = null;
    this.languages.clear();
    this.languageKeys = new WeakMap();
    this.queryCache.clear();
    this.failedQueries.clear();
  }
}
