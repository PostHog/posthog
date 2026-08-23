import { describe, expect, it } from "vitest";
import {
  type EnvironmentSetupPlan,
  emptyEnvironmentSetupPlan,
  envVarError,
  parseEnvVarText,
  planEnvironmentInput,
  setupSteps,
  setupStepsComplete,
  stepError,
  withEnvironmentName,
  withRepositories,
} from "./environmentSetup";

describe("environmentSetup", () => {
  const plan = (patch: Partial<EnvironmentSetupPlan> = {}) => ({
    ...emptyEnvironmentSetupPlan({ repository: "posthog/posthog" }),
    ...patch,
  });

  it("seeds both names from the repository", () => {
    const seeded = emptyEnvironmentSetupPlan({ repository: "posthog/posthog" });
    expect(seeded.environmentName).toBe("posthog cloud runs");
    expect(seeded.imageName).toBe("posthog toolchain");
  });

  it("keeps a typed environment name when the repositories change", () => {
    const typed = withEnvironmentName(plan(), "Internal APIs");
    const moved = withRepositories(typed, ["posthog/hogql"]);
    expect(moved.environmentName).toBe("Internal APIs");
    expect(moved.imageName).toBe("hogql toolchain");
  });

  it("keeps the first repository as the one the image is built for", () => {
    const two = withRepositories(plan(), ["posthog/posthog", "posthog/hogql"]);
    expect(two.repositories).toEqual(["posthog/posthog", "posthog/hogql"]);
    expect(two.imageName).toBe("posthog toolchain");
  });

  it("shows access only for a new environment, and image steps only when building", () => {
    expect(setupSteps(plan()).map((step) => step.key)).toEqual([
      "environment",
      "access",
      "image",
      "review",
    ]);
    expect(
      setupSteps(plan({ target: "existing", baseImage: "new" })).map(
        (step) => step.key,
      ),
    ).toEqual(["environment", "image", "tools", "setup", "review"]);
  });

  it("names what is unresolved on each step", () => {
    expect(stepError(plan({ environmentName: " " }), "environment")).toBe(
      "Give the environment a name.",
    );
    expect(stepError(plan({ target: "existing" }), "environment")).toBe(
      "Pick the environment to add to.",
    );
    expect(stepError(plan({ baseImage: "existing" }), "image")).toBe(
      "Pick an image.",
    );
    expect(
      stepError(
        plan({
          networkAccessLevel: "custom",
          allowedDomainsText: "http://nope",
        }),
        "access",
      ),
    ).toBe("Invalid domain: http://nope");
  });

  it("holds a custom access level that allows nothing", () => {
    expect(stepError(plan({ networkAccessLevel: "custom" }), "access")).toBe(
      "Add a domain, or pick another access level.",
    );
  });

  it("holds review until every visible step resolves", () => {
    expect(stepError(plan({ baseImage: "new", imageName: "" }), "review")).toBe(
      "Give the image a name.",
    );
    expect(setupStepsComplete(plan())).toEqual([true, true, true, true]);
  });

  it("carries the repositories and image onto the environment payload", () => {
    const input = planEnvironmentInput(
      withRepositories(plan(), ["posthog/posthog", "posthog/hogql"]),
      "image-1",
    );
    expect(input).toMatchObject({
      name: "posthog cloud runs",
      repositories: ["posthog/posthog", "posthog/hogql"],
      custom_image_id: "image-1",
      allowed_domains: [],
      include_default_domains: false,
    });
    expect(input.environment_variables).toBeUndefined();
  });

  it("keeps the allowlist only when the access level uses one", () => {
    const custom = planEnvironmentInput(
      plan({
        networkAccessLevel: "custom",
        allowedDomainsText: "github.com\n*.example.com",
      }),
      null,
    );
    expect(custom.allowed_domains).toEqual(["github.com", "*.example.com"]);
    expect(custom.include_default_domains).toBe(true);
  });

  it("sends only the rows that carry a variable", () => {
    const input = planEnvironmentInput(
      plan({
        envVars: [
          { id: "a", key: "OPENAI_API_KEY", value: "sk-test" },
          { id: "b", key: "  ", value: "" },
        ],
      }),
      null,
    );
    expect(input.environment_variables).toEqual({ OPENAI_API_KEY: "sk-test" });
  });

  it("reads pasted variables in the formats people carry them in", () => {
    expect(
      parseEnvVarText(
        [
          "# a comment",
          "export TOKEN=abc",
          'QUOTED="with spaces"',
          "EMPTY=",
          "not a variable",
          "URL=https://example.com/path?a=b",
        ].join("\n"),
      ),
    ).toEqual([
      { key: "TOKEN", value: "abc" },
      { key: "QUOTED", value: "with spaces" },
      { key: "EMPTY", value: "" },
      { key: "URL", value: "https://example.com/path?a=b" },
    ]);
  });

  it("rejects a malformed or repeated variable name", () => {
    const rows = [
      { id: "a", key: "GOOD", value: "1" },
      { id: "b", key: "2BAD", value: "1" },
      { id: "c", key: "GOOD", value: "2" },
      { id: "d", key: "", value: "orphan" },
    ];
    expect(envVarError(rows[0], rows)).toBe("GOOD is set twice.");
    expect(envVarError(rows[1], rows)).toContain("Letters, digits");
    expect(envVarError(rows[3], rows)).toBe("Name this variable.");
  });
});
