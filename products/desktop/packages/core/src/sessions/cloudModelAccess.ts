import type { Adapter, ModelAccess } from "@posthog/shared";

export type CloudModelAccess =
  | { kind: "posthog-gateway" }
  | { kind: "own-subscription"; adapter: Adapter };

export function cloudModelAccessFromState(
  state: Record<string, unknown>,
): CloudModelAccess {
  const claude = state.claude_model_access === "own-subscription";
  const codex = state.codex_model_access === "own-subscription";
  if (claude && codex)
    throw new Error("Select only one subscription for this run.");
  if (!claude && !codex) return { kind: "posthog-gateway" };
  const adapter = codex ? "codex" : "claude";
  if ((state.runtime_adapter ?? "claude") !== adapter) {
    throw new Error(
      `The ${adapter} subscription requires the ${adapter} runtime.`,
    );
  }
  return { kind: "own-subscription", adapter };
}

export function cloudAccessFor(
  access: CloudModelAccess,
  adapter: Adapter,
): ModelAccess {
  return access.kind === "own-subscription" && access.adapter === adapter
    ? "own-subscription"
    : "posthog-gateway";
}
