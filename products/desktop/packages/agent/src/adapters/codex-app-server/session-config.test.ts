import { isRestrictedModelOption } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildCodexModes,
  buildConfigOptions,
  CODEX_MODES,
  collaborationModeFor,
  DEFAULT_EFFORTS,
  modeApprovalPolicy,
  resolveCodexMode,
  SessionConfigState,
  sandboxPolicyFor,
} from "./session-config";

describe("modeApprovalPolicy", () => {
  it.each([
    ["read-only", "untrusted"],
    ["auto", "on-request"],
    ["full-access", "never"],
  ])("maps mode %s to approval policy %s", (mode, policy) => {
    expect(modeApprovalPolicy(mode)).toBe(policy);
  });

  it("returns undefined for an unknown mode", () => {
    expect(modeApprovalPolicy("nonsense")).toBeUndefined();
    expect(modeApprovalPolicy(undefined)).toBeUndefined();
  });

  it("every CODEX_MODES entry has a resolvable policy", () => {
    for (const mode of CODEX_MODES) {
      expect(modeApprovalPolicy(mode.id)).toBe(mode.approvalPolicy);
    }
  });
});

describe("sandboxPolicyFor", () => {
  it("restricts plan + read-only to a read-only sandbox", () => {
    expect(sandboxPolicyFor("plan")).toEqual({
      type: "readOnly",
      networkAccess: true,
    });
    expect(sandboxPolicyFor("read-only")).toEqual({
      type: "readOnly",
      networkAccess: true,
    });
  });

  it("restores an editable sandbox for auto + full-access (turn overrides are sticky)", () => {
    expect(sandboxPolicyFor("full-access")).toEqual({
      type: "dangerFullAccess",
    });
    expect(sandboxPolicyFor("auto")).toEqual(
      process.platform === "darwin"
        ? { type: "workspaceWrite", networkAccess: false }
        : { type: "dangerFullAccess" },
    );
  });

  it("returns undefined for unknown ids", () => {
    expect(sandboxPolicyFor("bypassPermissions")).toBeUndefined();
    expect(sandboxPolicyFor(undefined)).toBeUndefined();
  });
});

describe("buildCodexModes", () => {
  const sandboxFor = (platform: string, id: string) =>
    buildCodexModes(platform).find((m) => m.id === id)?.sandboxPolicy;

  it("gives auto the platform's editable sandbox (Seatbelt workspace-write on macOS, danger elsewhere)", () => {
    // Network stays restricted: egress still goes through codex's escalation prompt.
    expect(sandboxFor("darwin", "auto")).toEqual({
      type: "workspaceWrite",
      networkAccess: false,
    });
    expect(sandboxFor("linux", "auto")).toEqual({ type: "dangerFullAccess" });
    expect(sandboxFor("win32", "auto")).toEqual({ type: "dangerFullAccess" });
  });

  it.each(["darwin", "linux", "win32"])(
    "every mode states a full sandbox policy on %s so mode switches never inherit the previous sandbox",
    (platform) => {
      for (const mode of buildCodexModes(platform)) {
        expect(mode.sandboxPolicy).toBeDefined();
      }
    },
  );

  it("keeps plan + read-only on a read-only sandbox on every platform", () => {
    for (const platform of ["darwin", "linux", "win32"]) {
      expect(sandboxFor(platform, "plan")).toEqual({
        type: "readOnly",
        networkAccess: true,
      });
      expect(sandboxFor(platform, "read-only")).toEqual({
        type: "readOnly",
        networkAccess: true,
      });
    }
  });
});

describe("collaborationModeFor", () => {
  it("maps only Plan to codex's plan collaboration; everything else is default", () => {
    expect(collaborationModeFor("plan")).toBe("plan");
    expect(collaborationModeFor("read-only")).toBe("default");
    expect(collaborationModeFor("auto")).toBe("default");
    expect(collaborationModeFor("full-access")).toBe("default");
    expect(collaborationModeFor(undefined)).toBe("default");
  });
});

describe("resolveCodexMode", () => {
  it.each([
    ["read-only", "read-only"],
    ["auto", "auto"],
    ["full-access", "full-access"],
    ["bypassPermissions", "full-access"],
    ["default", "auto"],
    [undefined, "auto"],
  ])("maps host mode %s to codex mode %s", (mode, expected) => {
    expect(resolveCodexMode(mode)).toBe(expected);
  });
});

describe("SessionConfigState", () => {
  it("canonicalizes bypassPermissions during a live mode update", () => {
    const config = new SessionConfigState("gpt-5.5");

    config.setOption("mode", "bypassPermissions");

    expect(config.mode).toBe("full-access");
    expect(config.approvalPolicy()).toBe("never");
    expect(config.sandboxPolicy()).toEqual({ type: "dangerFullAccess" });
    expect(
      config.options.find((option) => option.category === "mode")?.currentValue,
    ).toBe("full-access");
  });

  it("uses gateway models when the app-server model list is stale", () => {
    const config = new SessionConfigState("gpt-5.5", undefined, [
      { id: "gpt-5.5", allowed: true },
      { id: "gpt-5.6-sol", allowed: true },
      { id: "gpt-5.6-terra", allowed: false },
    ]);

    config.loadModels([
      { id: "gpt-5.5", model: "gpt-5.5", displayName: "GPT-5.5" },
      {
        id: "gpt-5.6-terra",
        model: "gpt-5.6-terra",
        displayName: "GPT-5.6 Terra",
      },
    ]);

    const modelOption = config.options.find(
      (option) => option.category === "model",
    );
    const modelOptions =
      modelOption?.type === "select"
        ? (modelOption.options as Array<{
            name: string;
            value: string;
            _meta?: Record<string, unknown>;
          }>)
        : [];
    expect(modelOptions).toEqual([
      { name: "GPT-5.5", value: "gpt-5.5" },
      { name: "gpt-5.6-sol", value: "gpt-5.6-sol" },
      {
        name: "GPT-5.6 Terra",
        value: "gpt-5.6-terra",
        _meta: { "posthog.code/restrictedModel": true },
      },
    ]);

    config.setOption("model", "gpt-5.6-terra");

    expect(config.model).toBe("gpt-5.5");
    expect(
      isRestrictedModelOption(
        modelOptions.find((option) => option.value === "gpt-5.6-terra")?._meta,
      ),
    ).toBe(true);
  });

  it("keeps gateway models when the app-server model list fails", () => {
    const config = new SessionConfigState("gpt-5.5", undefined, [
      { id: "gpt-5.5", allowed: true },
      { id: "gpt-5.6-sol", allowed: true },
    ]);

    config.clearModels();

    const modelOption = config.options.find(
      (option) => option.category === "model",
    );
    expect(modelOption?.type === "select" ? modelOption.options : []).toEqual([
      { name: "gpt-5.5", value: "gpt-5.5" },
      { name: "gpt-5.6-sol", value: "gpt-5.6-sol" },
    ]);
  });
});

describe("buildConfigOptions", () => {
  const byCategory = (
    opts: ReturnType<typeof buildConfigOptions>,
    category: string,
  ) =>
    opts.find((o) => (o as { category: string }).category === category) as {
      currentValue: string;
      options: Array<{ value: string; name: string }>;
    };

  it("emits mode + model + thought_level selectors from the live lists", () => {
    const opts = buildConfigOptions({
      mode: "auto",
      model: "gpt-5.5",
      effort: "high",
      models: [
        { id: "gpt-5.5", name: "GPT-5.5" },
        { id: "gpt-5-mini", name: "GPT-5 mini" },
      ],
      efforts: ["low", "high"],
    });
    expect(opts.map((o) => (o as { category: string }).category)).toEqual([
      "mode",
      "model",
      "thought_level",
    ]);
    const model = byCategory(opts, "model");
    expect(model.currentValue).toBe("gpt-5.5");
    expect(model.options.map((o) => o.value)).toEqual([
      "gpt-5.5",
      "gpt-5-mini",
    ]);
  });

  it("surfaces the flattened codex presets (incl. Plan) with the current mode selected", () => {
    const mode = byCategory(
      buildConfigOptions({
        mode: "plan",
        model: "gpt-5.5",
        models: [],
        efforts: [],
      }),
      "mode",
    );
    expect(mode.currentValue).toBe("plan");
    expect(mode.options.map((o) => o.value)).toEqual([
      "plan",
      "read-only",
      "auto",
      "full-access",
    ]);
  });

  it("keeps the active model/effort selectable even if the lists omit them", () => {
    const opts = buildConfigOptions({
      mode: "auto",
      model: "gpt-5.5",
      effort: "max",
      models: [{ id: "gpt-5-mini", name: "GPT-5 mini" }],
      efforts: ["low", "high"],
    });
    const model = byCategory(opts, "model");
    const effort = byCategory(opts, "thought_level");
    expect(model.currentValue).toBe("gpt-5.5");
    expect(model.options.map((o) => o.value)).toContain("gpt-5.5");
    expect(effort.currentValue).toBe("max");
    expect(effort.options.map((o) => o.value)).toContain("max");
  });

  it("humanizes reasoning-effort labels (Title case) while keeping raw values", () => {
    const effort = byCategory(
      buildConfigOptions({
        mode: "auto",
        model: "gpt-5.5",
        effort: "high",
        models: [],
        efforts: ["low", "medium", "high"],
      }),
      "thought_level",
    );
    expect(effort.options).toEqual([
      { name: "Low", value: "low" },
      { name: "Medium", value: "medium" },
      { name: "High", value: "high" },
    ]);
  });

  it("falls back to the single current model and DEFAULT_EFFORTS when lists are empty", () => {
    const opts = buildConfigOptions({
      mode: "auto",
      model: "gpt-5.5",
      models: [],
      efforts: [],
    });
    expect(byCategory(opts, "model").options).toEqual([
      { name: "gpt-5.5", value: "gpt-5.5" },
    ]);
    expect(
      byCategory(opts, "thought_level").options.map((o) => o.value),
    ).toEqual(DEFAULT_EFFORTS);
  });
});
