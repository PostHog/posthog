import type {
  NetworkAccessLevel,
  SandboxEnvironment,
  SandboxEnvironmentInput,
} from "@posthog/shared/domain-types";

const DOMAIN_RE =
  /^(\*\.)?[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$/;
const ENV_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

export interface SandboxEnvironmentFormState {
  name: string;
  network_access_level: NetworkAccessLevel;
  allowed_domains_text: string;
  include_default_domains: boolean;
  environment_variables_text: string;
  private: boolean;
  custom_image_id: string | null;
}

export function isValidDomain(domain: string): boolean {
  return DOMAIN_RE.test(domain);
}

export function validateDomains(text: string): {
  domains: string[];
  errors: string[];
} {
  const domains: string[] = [];
  const errors: string[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (isValidDomain(trimmed)) {
      domains.push(trimmed);
    } else {
      errors.push(`Invalid domain: ${trimmed}`);
    }
  }
  return { domains, errors };
}

export function validateEnvVars(text: string): {
  vars: Record<string, string>;
  errors: string[];
} {
  const vars: Record<string, string> = {};
  const errors: string[] = [];
  for (const [i, line] of text.split("\n").entries()) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx <= 0) {
      errors.push(`Line ${i + 1}: missing '=' separator`);
      continue;
    }
    const key = trimmed.slice(0, eqIdx).trim();
    if (!ENV_KEY_RE.test(key)) {
      errors.push(`Line ${i + 1}: invalid key "${key}"`);
      continue;
    }
    vars[key] = trimmed.slice(eqIdx + 1).trim();
  }
  return { vars, errors };
}

export function emptyForm(): SandboxEnvironmentFormState {
  return {
    name: "",
    network_access_level: "full",
    allowed_domains_text: "",
    include_default_domains: true,
    environment_variables_text: "",
    private: true,
    custom_image_id: null,
  };
}

export function formFromEnv(
  env: SandboxEnvironment,
): SandboxEnvironmentFormState {
  return {
    name: env.name,
    network_access_level: env.network_access_level,
    allowed_domains_text: env.allowed_domains.join("\n"),
    include_default_domains: env.include_default_domains,
    environment_variables_text: "",
    private: env.private,
    custom_image_id: env.custom_image_id ?? null,
  };
}

export function buildSandboxEnvironmentInput(
  form: SandboxEnvironmentFormState,
  domains: string[],
  envVars: Record<string, string>,
): SandboxEnvironmentInput {
  const isCustom = form.network_access_level === "custom";
  return {
    name: form.name,
    network_access_level: form.network_access_level,
    allowed_domains: isCustom ? domains : [],
    include_default_domains: isCustom ? form.include_default_domains : false,
    private: form.private,
    repositories: [],
    custom_image_id: form.custom_image_id,
    ...(form.environment_variables_text.trim()
      ? { environment_variables: envVars }
      : {}),
  };
}
