import { injectable } from "inversify";
import {
  BUILT_IN_TEMPLATES,
  type CanvasTemplate,
  freeformSystemPromptFor,
} from "./canvasTemplates";
import type { ICanvasTemplatesService } from "./services";
import type { CanvasTemplateSummary } from "./templateSchemas";

// Owns the canvas templates — the per-template agent context (system prompt)
// that anchors how the gen-UI agent builds. Built-ins are seeded here; the
// registry is a Map so user-defined templates can be added later (the store
// would back them; built-ins stay read-only). Host-agnostic (pure prompt
// strings), so it lives in @posthog/core and binds via canvasCoreModule.
@injectable()
export class CanvasTemplatesService implements ICanvasTemplatesService {
  private readonly templates = new Map<string, CanvasTemplate>(
    BUILT_IN_TEMPLATES.map((t) => [t.id, t]),
  );

  list(): CanvasTemplateSummary[] {
    return [...this.templates.values()].map(
      ({ systemPrompt: _p, ...rest }) => ({
        ...rest,
      }),
    );
  }

  get(id: string): CanvasTemplate | undefined {
    return this.templates.get(id);
  }

  /** The freeform (React) prompt for a template, falling back to the generic sandbox. */
  freeformSystemPromptFor(id: string | undefined): string {
    return freeformSystemPromptFor(id);
  }
}
