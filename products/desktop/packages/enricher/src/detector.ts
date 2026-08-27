import {
  findFlagAssignments as _findFlagAssignments,
  findFunctions as _findFunctions,
  findInitCalls as _findInitCalls,
  findPostHogCalls as _findPostHogCalls,
} from "./call-detector.js";
import { findImports as _findImports } from "./import-resolver.js";
import { ParserManager } from "./parser-manager.js";
import type {
  DetectionConfig,
  FlagAssignment,
  FunctionInfo,
  ImportEdge,
  LocalWrapper,
  ParseContext,
  PostHogCall,
  PostHogInitCall,
  VariantBranch,
} from "./types.js";
import { findVariantBranches as _findVariantBranches } from "./variant-detector.js";
import { findWrappers as _findWrappers } from "./wrapper-detector.js";

export class PostHogDetector {
  private pm = new ParserManager();

  updateConfig(config: DetectionConfig): void {
    this.pm.updateConfig(config);
  }

  isSupported(langId: string): boolean {
    return this.pm.isSupported(langId);
  }

  get supportedLanguages(): string[] {
    return this.pm.supportedLanguages;
  }

  async findPostHogCalls(
    source: string,
    languageId: string,
    context?: ParseContext,
  ): Promise<PostHogCall[]> {
    return _findPostHogCalls(this.pm, source, languageId, context);
  }

  async findInitCalls(
    source: string,
    languageId: string,
  ): Promise<PostHogInitCall[]> {
    return _findInitCalls(this.pm, source, languageId);
  }

  async findFunctions(
    source: string,
    languageId: string,
  ): Promise<FunctionInfo[]> {
    return _findFunctions(this.pm, source, languageId);
  }

  async findVariantBranches(
    source: string,
    languageId: string,
  ): Promise<VariantBranch[]> {
    return _findVariantBranches(this.pm, source, languageId);
  }

  async findFlagAssignments(
    source: string,
    languageId: string,
  ): Promise<FlagAssignment[]> {
    return _findFlagAssignments(this.pm, source, languageId);
  }

  async findWrappers(
    source: string,
    languageId: string,
  ): Promise<LocalWrapper[]> {
    return _findWrappers(this.pm, source, languageId);
  }

  async findImports(
    source: string,
    languageId: string,
    callerAbsPath: string,
  ): Promise<ImportEdge[]> {
    return _findImports(this.pm, source, languageId, callerAbsPath);
  }

  dispose(): void {
    this.pm.dispose();
  }
}
