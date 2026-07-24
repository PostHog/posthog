import type {
  SessionConfigOption,
  SessionConfigSelectOption,
} from "@agentclientprotocol/sdk";
import {
  CODEX_MODE_PRESETS,
  type CodexModePreset,
  type ExecutionMode,
  resolveCloudInitialPermissionMode,
  restrictedModelMeta,
} from "@posthog/shared";
import {
  type GatewayModel,
  isOpenAIModel,
  type ModelInfo,
} from "../../gateway-models";
import { getReasoningEffortOptions } from "./models";

/**
 * Session config + mode synthesis for the codex app-server adapter. The native
 * app-server has no "mode" RPC (a thread is configured by `approvalPolicy` +
 * `sandbox`), so modes are synthesized here and applied per-turn.
 */

/**
 * Per-turn sandbox the mode maps to (subset of codex's SandboxPolicy). This is
 * what makes read-only/plan actually block edits — `approvalPolicy` alone is
 * neutralized because the process spawns editable.
 */
export type CodexSandboxPolicy =
  | { type: "readOnly"; networkAccess: boolean }
  | { type: "workspaceWrite"; networkAccess: boolean; writableRoots?: string[] }
  | { type: "dangerFullAccess" };

export interface CodexMode {
  id: string;
  name: string;
  description: string;
  /** codex AskForApproval the mode maps to, applied per-turn on turn/start. */
  approvalPolicy: string;
  /**
   * Per-turn sandbox, sent on every turn/start. codex keeps turn overrides for
   * subsequent turns, so every mode states its full sandbox — omitting it would
   * leave the previous mode's sandbox active (e.g. plan's readOnly bleeding
   * into auto, which then prompts for every command and edit). Only applied off
   * the cloud sandbox, where a non-danger policy would re-engage the
   * unavailable linux-sandbox and panic.
   */
  sandboxPolicy: CodexSandboxPolicy;
  /**
   * codex's native collaboration mode (per-turn on `turn/start`). "plan" unlocks
   * plan proposals + `request_user_input`; everything else runs "default".
   */
  collaborationMode?: "plan" | "default";
}

/**
 * The editable sandbox for a platform, mirroring spawn.ts's `sandbox_mode`:
 * macOS Seatbelt supports workspace-write; linux/windows have no sandbox
 * launcher (a managed sandbox would panic), so danger-full-access. Network
 * stays restricted so commands that need egress still go through codex's
 * escalation prompt — broadening that is a security decision, not a UX fix.
 */
function editableSandboxPolicy(platform: string): CodexSandboxPolicy {
  return platform === "darwin"
    ? { type: "workspaceWrite", networkAccess: false }
    : { type: "dangerFullAccess" };
}

// Flattened Claude-style presets: the `{id, name, description}` literals live
// in @posthog/shared (one copy for every picker); this map owns the behavior.
// Restriction is driven by approvalPolicy + sandboxPolicy: plan/read-only block
// edits, auto/full-access restore the platform's editable sandbox.
function modePolicies(
  platform: string,
): Record<
  CodexModePreset["id"],
  Pick<CodexMode, "approvalPolicy" | "sandboxPolicy" | "collaborationMode">
> {
  return {
    plan: {
      approvalPolicy: "on-request",
      sandboxPolicy: { type: "readOnly", networkAccess: true },
      collaborationMode: "plan",
    },
    "read-only": {
      approvalPolicy: "untrusted",
      sandboxPolicy: { type: "readOnly", networkAccess: true },
    },
    auto: {
      approvalPolicy: "on-request",
      sandboxPolicy: editableSandboxPolicy(platform),
    },
    "full-access": {
      approvalPolicy: "never",
      sandboxPolicy: { type: "dangerFullAccess" },
    },
  };
}

/** Test seam: the mode table for a given platform; CODEX_MODES uses the live one. */
export function buildCodexModes(platform: string): CodexMode[] {
  const policies = modePolicies(platform);
  return CODEX_MODE_PRESETS.map((preset) => ({
    ...preset,
    ...policies[preset.id],
  }));
}

export const CODEX_MODES: CodexMode[] = buildCodexModes(process.platform);

export const DEFAULT_MODE = "auto";

export function modeApprovalPolicy(
  modeId: string | undefined,
): string | undefined {
  return CODEX_MODES.find((m) => m.id === modeId)?.approvalPolicy;
}

/** Per-turn sandbox for a mode id (sent every turn — codex turn overrides are sticky). */
export function sandboxPolicyFor(
  modeId: string | undefined,
): CodexSandboxPolicy | undefined {
  return CODEX_MODES.find((m) => m.id === modeId)?.sandboxPolicy;
}

/** codex collaboration mode for a preset — "plan" only for Plan, else "default". */
export function collaborationModeFor(
  modeId: string | undefined,
): "plan" | "default" {
  return (
    CODEX_MODES.find((m) => m.id === modeId)?.collaborationMode ?? "default"
  );
}

/**
 * Resolve a host permission mode or live picker value to a codex mode. A
 * recognized mode is honored; Claude's bypass mode maps to Codex full access.
 * Other unknown modes fall back to default.
 */
export function resolveCodexMode(mode: string | undefined): string {
  if (!mode) return DEFAULT_MODE;
  return resolveCloudInitialPermissionMode("codex", mode as ExecutionMode);
}

/** Codex's standard reasoning efforts; used when model/list doesn't expose them. */
export const DEFAULT_EFFORTS = ["low", "medium", "high"];

// Display labels for reasoning efforts; the host renders `name` verbatim.
const EFFORT_LABELS: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra High",
  max: "Max",
};

function humanizeEffort(effort: string): string {
  return EFFORT_LABELS[effort] ?? effort;
}

/** The current selector values `buildConfigOptions` projects into ACP options. */
export interface ConfigSelectors {
  /** Current permission/collaboration preset id (one of CODEX_MODES). */
  mode: string;
  model: string;
  effort?: string;
  /** From model/list; falls back to the single current model when empty. */
  models: Array<{
    id: string;
    name: string;
    _meta?: Record<string, unknown>;
  }>;
  efforts: string[];
}

/** Builds the ACP configOptions (mode + model + thought_level) the host renders. */
export function buildConfigOptions(s: ConfigSelectors): SessionConfigOption[] {
  const baseModels = s.models.length
    ? s.models
    : [{ id: s.model, name: s.model }];
  // Ensure the active model stays selectable, else currentValue points at nothing.
  const models = baseModels.some((m) => m.id === s.model)
    ? baseModels
    : [...baseModels, { id: s.model, name: s.model }];
  const baseEfforts = s.efforts.length ? s.efforts : DEFAULT_EFFORTS;
  const currentEffort = s.effort ?? baseEfforts[0];
  const efforts = baseEfforts.includes(currentEffort)
    ? baseEfforts
    : [...baseEfforts, currentEffort];
  return [
    {
      type: "select",
      id: "mode",
      name: "Mode",
      category: "mode",
      currentValue: s.mode,
      options: CODEX_MODES.map((m) => ({
        name: m.name,
        value: m.id,
        description: m.description,
      })),
    } as unknown as SessionConfigOption,
    {
      type: "select",
      id: "model",
      name: "Model",
      category: "model",
      currentValue: s.model,
      options: models.map(
        (m): SessionConfigSelectOption => ({
          name: m.name,
          value: m.id,
          ...(m._meta ? { _meta: m._meta } : {}),
        }),
      ),
    } as unknown as SessionConfigOption,
    {
      type: "select",
      id: "effort",
      name: "Reasoning effort",
      category: "thought_level",
      currentValue: currentEffort,
      options: efforts.map((e) => ({ name: humanizeEffort(e), value: e })),
    } as unknown as SessionConfigOption,
  ];
}

/** A model entry from the app-server's `model/list` (loosely typed). */
export interface RawModel {
  id?: string;
  model?: string;
  displayName?: string;
  hidden?: boolean;
  supportedReasoningEfforts?: Array<{ reasoningEffort?: string } | string>;
}

/**
 * Stateful holder for a codex session's model / effort / mode selectors and the
 * ACP `configOptions` derived from them — synthesizing the Claude-style picker
 * the app-server has no native concept of, rebuilt on every change.
 */
export class SessionConfigState {
  private _model: string;
  private _effort?: string;
  private _mode = DEFAULT_MODE;
  private models: Array<{
    id: string;
    name: string;
    _meta?: Record<string, unknown>;
  }> = [];
  private efforts: string[] = [];
  private _options: SessionConfigOption[] = [];
  private readonly gatewayModels?: ReadonlyArray<ModelInfo>;
  private readonly allowedModelIds?: ReadonlySet<string>;

  constructor(
    model: string,
    effort?: string,
    gatewayModels?: ReadonlyArray<ModelInfo>,
  ) {
    this._model = model;
    this._effort = effort;
    this.gatewayModels = gatewayModels?.length ? gatewayModels : undefined;
    this.allowedModelIds = this.gatewayModels
      ? new Set(
          this.gatewayModels
            .filter((gatewayModel) => gatewayModel.allowed)
            .map((gatewayModel) => gatewayModel.id),
        )
      : undefined;
    this.rebuild();
  }

  get model(): string {
    return this._model;
  }
  get effort(): string | undefined {
    return this._effort;
  }
  get mode(): string {
    return this._mode;
  }
  get options(): SessionConfigOption[] {
    return this._options;
  }

  /** Apply the host's initial approval mode (from `_meta.permissionMode`). */
  setInitialMode(permissionMode: string | undefined): void {
    this._mode = resolveCodexMode(permissionMode);
    this.rebuild();
  }

  /** Apply a `setSessionConfigOption` change; returns whether the mode changed. */
  setOption(
    configId: string | undefined,
    value: unknown,
  ): { modeChanged: boolean } {
    let modeChanged = false;
    if (typeof value === "string") {
      if (
        configId === "model" &&
        (!this.gatewayModels || this.allowedModelIds?.has(value))
      ) {
        this._model = value;
      } else if (configId === "effort") this._effort = value;
      else if (configId === "mode") {
        this._mode = resolveCodexMode(value);
        modeChanged = true;
      }
    }
    this.rebuild();
    return { modeChanged };
  }

  /**
   * Populate the model + effort selectors from a `model/list` `data` array. The
   * gateway also serves Claude models, so drop non-OpenAI ones; it doesn't
   * populate efforts, so fall back to the shared codex model→effort map.
   */
  loadModels(rawModels: RawModel[]): void {
    const liveModels = rawModels
      .filter((m) => !m?.hidden)
      .filter((m) => isOpenAIModel(m as unknown as GatewayModel))
      .map((m) => ({
        id: (m.id ?? m.model) as string,
        name: (m.displayName ?? m.id ?? m.model) as string,
      }));
    if (this.gatewayModels) {
      const liveModelsById = new Map(
        liveModels.map((model) => [model.id, model]),
      );
      this.models = this.gatewayModels.map((gatewayModel) => ({
        ...(liveModelsById.get(gatewayModel.id) ?? {
          id: gatewayModel.id,
          name: gatewayModel.id,
        }),
        ...(gatewayModel.allowed ? {} : { _meta: restrictedModelMeta() }),
      }));
    } else {
      this.models = liveModels;
    }
    const current = rawModels.find(
      (m) => m.id === this._model || m.model === this._model,
    );
    const liveEfforts = (current?.supportedReasoningEfforts ?? [])
      .map((e) => (typeof e === "string" ? e : e?.reasoningEffort))
      .filter((e): e is string => typeof e === "string");
    this.efforts = liveEfforts.length
      ? liveEfforts
      : getReasoningEffortOptions(this._model).map((o) => o.value);
    this.rebuild();
  }

  /** Reset the model/effort lists (model/list failed); keeps the current model. */
  clearModels(): void {
    this.models =
      this.gatewayModels?.map((gatewayModel) => ({
        id: gatewayModel.id,
        name: gatewayModel.id,
        ...(gatewayModel.allowed ? {} : { _meta: restrictedModelMeta() }),
      })) ?? [];
    this.efforts = [];
    this.rebuild();
  }

  /**
   * codex's per-turn `collaborationMode`: `{ mode, settings: { model } }`. The
   * model must be a string (not the null in collaborationMode/list output).
   */
  collaborationModeForTurn(): unknown {
    return {
      mode: collaborationModeFor(this._mode),
      settings: { model: this._model },
    };
  }

  approvalPolicy(): string | undefined {
    return modeApprovalPolicy(this._mode);
  }

  sandboxPolicy(): CodexSandboxPolicy | undefined {
    return sandboxPolicyFor(this._mode);
  }

  private rebuild(): void {
    this._options = buildConfigOptions({
      mode: this._mode,
      model: this._model,
      effort: this._effort,
      models: this.models,
      efforts: this.efforts,
    });
  }
}
