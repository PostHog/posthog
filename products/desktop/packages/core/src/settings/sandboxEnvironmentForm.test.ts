import type { SandboxEnvironment } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  buildSandboxEnvironmentInput,
  emptyForm,
  formFromEnv,
  isValidDomain,
  validateDomains,
  validateEnvVars,
} from "./sandboxEnvironmentForm";

describe("isValidDomain", () => {
  it("accepts a bare domain", () => {
    expect(isValidDomain("github.com")).toBe(true);
  });

  it("accepts a wildcard subdomain", () => {
    expect(isValidDomain("*.example.com")).toBe(true);
  });

  it("rejects a URL with scheme", () => {
    expect(isValidDomain("https://github.com")).toBe(false);
  });
});

describe("validateDomains", () => {
  it("collects valid domains and skips blank lines", () => {
    const result = validateDomains("github.com\n\n*.example.com\n");
    expect(result.domains).toEqual(["github.com", "*.example.com"]);
    expect(result.errors).toEqual([]);
  });

  it("reports invalid domains", () => {
    const result = validateDomains("github.com\nnot a domain");
    expect(result.domains).toEqual(["github.com"]);
    expect(result.errors).toEqual(["Invalid domain: not a domain"]);
  });
});

describe("validateEnvVars", () => {
  it("parses KEY=value lines and skips comments", () => {
    const result = validateEnvVars("# comment\nFOO=bar\nBAZ=qux");
    expect(result.vars).toEqual({ FOO: "bar", BAZ: "qux" });
    expect(result.errors).toEqual([]);
  });

  it("reports a missing separator", () => {
    const result = validateEnvVars("FOO");
    expect(result.errors).toEqual(["Line 1: missing '=' separator"]);
  });

  it("reports an invalid key", () => {
    const result = validateEnvVars("1FOO=bar");
    expect(result.errors).toEqual(['Line 1: invalid key "1FOO"']);
  });
});

describe("emptyForm", () => {
  it("defaults to full network access", () => {
    expect(emptyForm().network_access_level).toBe("full");
  });
});

describe("formFromEnv", () => {
  it("joins allowed domains onto separate lines and clears env vars", () => {
    const env = {
      id: "env1",
      name: "Internal",
      network_access_level: "custom",
      allowed_domains: ["a.com", "b.com"],
      include_default_domains: false,
      private: true,
    } as unknown as SandboxEnvironment;
    const form = formFromEnv(env);
    expect(form.allowed_domains_text).toBe("a.com\nb.com");
    expect(form.environment_variables_text).toBe("");
  });
});

describe("buildSandboxEnvironmentInput", () => {
  it("includes domains and default flag only when custom", () => {
    const form = {
      ...emptyForm(),
      name: "Custom",
      network_access_level: "custom" as const,
      include_default_domains: true,
    };
    const input = buildSandboxEnvironmentInput(form, ["a.com"], {});
    expect(input.allowed_domains).toEqual(["a.com"]);
    expect(input.include_default_domains).toBe(true);
  });

  it("drops domains and default flag when not custom", () => {
    const form = { ...emptyForm(), name: "Full" };
    const input = buildSandboxEnvironmentInput(form, ["a.com"], {});
    expect(input.allowed_domains).toEqual([]);
    expect(input.include_default_domains).toBe(false);
  });

  it("omits environment_variables when the text is blank", () => {
    const form = { ...emptyForm(), name: "Full" };
    const input = buildSandboxEnvironmentInput(form, [], { FOO: "bar" });
    expect("environment_variables" in input).toBe(false);
  });

  it("includes environment_variables when the text is present", () => {
    const form = {
      ...emptyForm(),
      name: "Full",
      environment_variables_text: "FOO=bar",
    };
    const input = buildSandboxEnvironmentInput(form, [], { FOO: "bar" });
    expect(input.environment_variables).toEqual({ FOO: "bar" });
  });
});
