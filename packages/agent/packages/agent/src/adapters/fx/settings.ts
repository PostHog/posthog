import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const FX_PROVIDER_NAME = "posthog";
export const FX_GATEWAY_KEY_ENV = "POSTHOG_FX_GATEWAY_KEY";

export interface FxProviderSettings {
  baseUrl: string;
  model: string;
  contextWindow?: number;
  supportsVision?: boolean;
}

type JsonObject = Record<string, unknown>;

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function fxSettingsPath(home: string = homedir()): string {
  return join(home, ".fx", "settings.json");
}

function withoutPermissionRules(settings: JsonObject): JsonObject {
  const { permission: _permission, ...rest } = settings;
  return rest;
}

export function applyFxProviderSettings(
  existing: JsonObject,
  provider: FxProviderSettings,
): JsonObject {
  const providers = isJsonObject(existing.providers) ? existing.providers : {};
  const models = isJsonObject(existing.models) ? existing.models : {};
  const workspaces = isJsonObject(existing.workspaces)
    ? Object.fromEntries(
        Object.entries(existing.workspaces).map(([root, workspace]) => [
          root,
          isJsonObject(workspace)
            ? withoutPermissionRules(workspace)
            : workspace,
        ]),
      )
    : existing.workspaces;
  return {
    ...withoutPermissionRules(existing),
    ...(workspaces !== undefined && { workspaces }),
    provider: FX_PROVIDER_NAME,
    auto_upgrade: false,
    providers: {
      ...providers,
      [FX_PROVIDER_NAME]: {
        protocol: "openai-chat-completions",
        base_url: provider.baseUrl,
        auth: { type: "bearer", env: FX_GATEWAY_KEY_ENV },
        model_metadata: {
          [provider.model]: {
            supports_tool_use: true,
            supports_vision: provider.supportsVision ?? false,
            ...(provider.contextWindow && {
              context_window: provider.contextWindow,
            }),
          },
        },
      },
    },
    models: { ...models, [FX_PROVIDER_NAME]: provider.model },
  };
}

async function readSettings(path: string): Promise<JsonObject> {
  let raw: string;
  try {
    raw = await readFile(path, "utf8");
  } catch {
    return {};
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    return isJsonObject(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export async function writeFxProviderSettings(
  provider: FxProviderSettings,
  path: string = fxSettingsPath(),
): Promise<void> {
  const settings = applyFxProviderSettings(await readSettings(path), provider);
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const tempPath = `${path}.${process.pid}.tmp`;
  await writeFile(tempPath, `${JSON.stringify(settings, null, 2)}\n`, {
    mode: 0o600,
  });
  await rename(tempPath, path);
}
