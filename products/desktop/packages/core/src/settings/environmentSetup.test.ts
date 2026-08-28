import { describe, expect, it } from "vitest";
import {
  type EnvironmentSetupPlan,
  emptyEnvironmentSetupPlan,
  envVarError,
  isPlanDirty,
  isValidDomain,
  parseEnvVarText,
  planEnvironmentInput,
  planImageInput,
  setupSteps,
  setupStepsComplete,
  splitPastedEnvVars,
  stepError,
  validateDomains,
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

  it("carries the repository and privacy onto the image payload", () => {
    const input = planImageInput(plan({ imageName: " CI toolchain " }));
    expect(input.name).toBe("CI toolchain");
    expect(input.repository).toBe("posthog/posthog");
    expect(input.private).toBe(true);
    expect(input.description).toContain("posthog/posthog");

    const bare = planImageInput(
      plan({ repositories: [], private: false, imageName: "Bare" }),
    );
    expect(bare).not.toHaveProperty("repository");
    expect(bare).not.toHaveProperty("private");
  });

  it("marks a plan dirty only when a field actually changed", () => {
    const saved = plan({
      envVars: [{ id: "a", key: "TOKEN", value: "abc" }],
      setupLines: [{ id: "s", value: "pnpm install" }],
    });
    expect(isPlanDirty({ ...saved }, saved)).toBe(false);
    expect(
      isPlanDirty({ ...saved, repositories: ["posthog/hogql"] }, saved),
    ).toBe(true);
    expect(
      isPlanDirty(
        { ...saved, envVars: [{ id: "a", key: "TOKEN", value: "xyz" }] },
        saved,
      ),
    ).toBe(true);
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

  it("keeps a pasted .env usable by leaving out the keys the sandbox manages", () => {
    const { entries, skipped } = splitPastedEnvVars(
      [
        "OPENAI_API_KEY=sk-example",
        "GITHUB_TOKEN=ghp-example",
        "GIT_AUTHOR_NAME=Jane",
        "NODE_OPTIONS=--max-old-space-size=4096",
        "DATABASE_URL=postgres://example.com/app",
      ].join("\n"),
    );
    expect(entries).toEqual([
      { key: "OPENAI_API_KEY", value: "sk-example" },
      { key: "DATABASE_URL", value: "postgres://example.com/app" },
    ]);
    expect(skipped).toEqual([
      "GITHUB_TOKEN",
      "GIT_AUTHOR_NAME",
      "NODE_OPTIONS",
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

  it.each([
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "POSTHOG_PERSONAL_API_KEY",
    "POSTHOG_IMAGE_TOOLS",
  ])("rejects the reserved key %s before submit", (key) => {
    const rows = [{ id: "a", key, value: "x" }];
    expect(envVarError(rows[0], rows)).toContain("reserved by PostHog");
  });

  it.each([
    "NODE_OPTIONS",
    "BASH_ENV",
    "LD_PRELOAD",
    "DYLD_PRINT_LIBRARIES",
    "GIT_DIR",
  ])("rejects the blocked key %s before submit", (key) => {
    const rows = [{ id: "a", key, value: "x" }];
    expect(envVarError(rows[0], rows)).toContain("not allowed");
  });
});

describe("validateDomains", () => {
  it.each([
    ["github.com", true],
    ["*.example.com", true],
    ["https://github.com", false],
  ])("isValidDomain(%s) -> %s", (domain, expected) => {
    expect(isValidDomain(domain)).toBe(expected);
  });

  it("collects valid domains, skips blank lines, and reports invalid ones", () => {
    const result = validateDomains("github.com\n\n*.example.com\nnot a domain");
    expect(result.domains).toEqual(["github.com", "*.example.com"]);
    expect(result.errors).toEqual(["Invalid domain: not a domain"]);
  });
});
