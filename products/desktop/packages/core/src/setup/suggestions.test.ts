import {
  buildPosthogSetupSuggestion,
  buildSdkHealthSuggestion,
  buildStaleFlagSuggestion,
  type StaleFlagPayload,
} from "@posthog/core/setup/suggestions";
import { describe, expect, it } from "vitest";

// The scan sees the same thing for all three: no recorded calls, plus
// references. Nothing in the payload tells them apart, so the suggestion has to
// be safe for every one of them.
const FLAG_REALITIES: [label: string, flag: StaleFlagPayload][] = [
  [
    "a live flag whose SDK evaluates locally",
    {
      flagKey: "checkout-v2",
      referenceCount: 1,
      references: [{ file: "src/checkout.ts", line: 10, method: "isEnabled" }],
    },
  ],
  [
    "a flag that really is a deterministic cleanup candidate",
    {
      flagKey: "legacy-banner",
      referenceCount: 2,
      references: [
        { file: "src/a.ts", line: 4, method: "isFeatureEnabled" },
        { file: "src/b.ts", line: 22, method: "useFeatureFlag" },
      ],
    },
  ],
  [
    "a flag on an ambiguous partial rollout",
    {
      flagKey: "pricing-test",
      referenceCount: 7,
      references: [
        { file: "src/pricing.ts", line: 31, method: "getFeatureFlag" },
        { file: "src/plans.tsx", line: 8, method: "useFeatureFlag" },
      ],
    },
  ],
];

function renderedText(flag: StaleFlagPayload): string {
  const task = buildStaleFlagSuggestion(flag);
  if (!task) throw new Error("expected a suggestion");
  return [task.title, task.description, task.impact, task.recommendation].join(
    "\n",
  );
}

describe("buildStaleFlagSuggestion", () => {
  const flag = FLAG_REALITIES[1][1];

  it("derives a stable id from the flag key so dismissal sticks", () => {
    expect(buildStaleFlagSuggestion(flag)?.id).toBe(
      "posthog-stale-flag-legacy-banner",
    );
  });

  it("anchors file/lineHint to the first reference", () => {
    const task = buildStaleFlagSuggestion(flag);
    expect(task?.file).toBe("src/a.ts");
    expect(task?.lineHint).toBe(4);
  });

  it("withholds the suggestion when the scan found no references to hand over", () => {
    expect(
      buildStaleFlagSuggestion({
        flagKey: "no-refs",
        referenceCount: 0,
        references: [],
      }),
    ).toBeNull();
  });

  it.each(FLAG_REALITIES)(
    "states only what the scan observed for %s",
    (_label, flag) => {
      const task = buildStaleFlagSuggestion(flag);
      const plural = flag.referenceCount === 1 ? "place" : "places";

      expect(task?.description).toContain(
        `no calls to \`${flag.flagKey}\` in the last 30 days`,
      );
      expect(task?.description).toContain(
        `references it in ${flag.referenceCount} ${plural}`,
      );
      expect(task?.description).toContain("not proof the flag is unused");

      const text = renderedText(flag);
      expect(text).not.toMatch(/winning branch|inline the |remove the flag/i);
      expect(text).not.toMatch(/n[o'’]t? been evaluated|was not evaluated/i);
    },
  );

  it.each(FLAG_REALITIES)(
    "hands the cleanup skill the identity, references and pre-edit checks for %s",
    (_label, flag) => {
      const prompt = buildStaleFlagSuggestion(flag)?.prompt ?? "";

      expect(prompt.startsWith("/cleaning-up-stale-feature-flags")).toBe(true);
      expect(prompt).toContain(`"${flag.flagKey}"`);
      for (const ref of flag.references) {
        expect(prompt).toContain(`- ${ref.file}:${ref.line} (${ref.method})`);
      }

      const hidden = flag.referenceCount - flag.references.length;
      if (hidden > 0) expect(prompt).toContain(`…and ${hidden} more.`);
      else expect(prompt).not.toContain("more.");

      expect(prompt).toContain("Before you edit any code:");
      expect(prompt).toContain("current definition and status in PostHog");
      expect(prompt).toContain("evaluation runtime and contexts");
      expect(prompt).toContain("check for blockers");
      expect(prompt).toContain("Stop and report instead of editing");
      expect(prompt).toContain("Do not change the flag in PostHog.");
      expect(prompt).not.toMatch(/winning branch|inline the |remove the flag/i);
    },
  );
});

describe("buildSdkHealthSuggestion", () => {
  it("is a stable enricher posthog_setup suggestion", () => {
    const task = buildSdkHealthSuggestion();
    expect(task).toMatchObject({
      id: "posthog-sdk-health",
      source: "enricher",
      category: "posthog_setup",
      prompt: "/diagnosing-sdk-health",
    });
  });
});

describe("buildPosthogSetupSuggestion", () => {
  it("returns the install suggestion when not installed", () => {
    const task = buildPosthogSetupSuggestion("not_installed");
    expect(task.id).toBe("posthog-setup");
    expect(task.prompt).toBe("/instrument-integration");
  });

  it("returns the finish-init suggestion when installed but not initialized", () => {
    const task = buildPosthogSetupSuggestion("installed_no_init");
    expect(task.id).toBe("posthog-finish-init");
    expect(task.prompt).toContain("skip install steps");
  });
});
