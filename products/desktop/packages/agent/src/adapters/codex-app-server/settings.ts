import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

/**
 * Codex settings parsed from ~/.codex/config.toml and project-level config.
 *
 * Mirrors the shape of ClaudeCodeSettings so both adapters have a
 * consistent settings interface.
 */
export interface CodexSettings {
  model?: string;
  personality?: string;
  modelReasoningEffort?: string;
  trustLevel?: string;
  // Names of every `[mcp_servers.<name>]` section declared in the user's config.toml
  mcpServerNames: string[];
}

/**
 * SettingsManager for Codex sessions.
 *
 * Reads from ~/.codex/config.toml (user-level) and respects
 * per-project trust configuration. Has the same public interface
 * as Claude's SettingsManager so both can satisfy BaseSession.
 */
export class CodexSettingsManager {
  private cwd: string;
  private settings: CodexSettings = { mcpServerNames: [] };

  constructor(cwd: string) {
    this.cwd = cwd;
    this.loadSettings();
  }

  async initialize(): Promise<void> {
    // No-op: settings are loaded in the constructor. Kept async to
    // satisfy the BaseSettingsManager interface.
  }

  private getConfigPath(): string {
    return path.join(os.homedir(), ".codex", "config.toml");
  }

  private loadSettings(): void {
    const configPath = this.getConfigPath();
    try {
      const content = fs.readFileSync(configPath, "utf-8");
      this.settings = parseCodexToml(content, this.cwd);
    } catch {
      this.settings = { mcpServerNames: [] };
    }
  }

  getSettings(): CodexSettings {
    return this.settings;
  }

  getCwd(): string {
    return this.cwd;
  }

  async setCwd(cwd: string): Promise<void> {
    if (this.cwd === cwd) return;
    this.cwd = cwd;
    this.loadSettings();
  }

  dispose(): void {
    // No-op: no resources to release. Kept to satisfy the BaseSettingsManager interface.
  }
}

/**
 * Extracts the server name from a `mcp_servers.<name>...` section path, taking
 * only the first key segment. A nested table like `mcp_servers.foo.env`
 * describes the `env` field of server `foo`, not a separate server, so it must
 * collapse to `foo`. Treating it as its own server emits
 * `mcp_servers.foo.env.enabled=false`, which sets a boolean on the string-typed
 * env map and makes codex reject the whole config (it then crashes and the
 * host silently falls back to Claude). Quoted segments (`"a.b"`) keep their dots.
 */
function firstMcpServerName(sectionPath: string): string | null {
  const trimmed = sectionPath.trim();
  if (!trimmed) return null;
  const quoted = trimmed.match(/^(["'])(.*?)\1/);
  if (quoted) return quoted[2] ?? null;
  const dotIndex = trimmed.indexOf(".");
  return dotIndex === -1 ? trimmed : trimmed.slice(0, dotIndex);
}

/**
 * Minimal TOML parser for codex config.toml.
 * Handles flat key=value pairs and [projects."path"] sections.
 * Does NOT handle full TOML spec — only what codex config uses.
 */
function parseCodexToml(content: string, cwd: string): CodexSettings {
  const settings: CodexSettings = { mcpServerNames: [] };
  const mcpServerNames = new Set<string>();
  let currentSection = "";

  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    // Section header: [projects."/some/path"] or [section]
    const sectionMatch = trimmed.match(/^\[(.+)\]$/);
    if (sectionMatch) {
      currentSection = sectionMatch[1] ?? "";
      if (currentSection.startsWith("mcp_servers.")) {
        const serverName = firstMcpServerName(
          currentSection.slice("mcp_servers.".length),
        );
        if (serverName) mcpServerNames.add(serverName);
      }
      continue;
    }

    // Key = value
    const kvMatch = trimmed.match(/^(\w+)\s*=\s*(.+)$/);
    if (!kvMatch) continue;

    const key = kvMatch[1];
    let value = kvMatch[2]?.trim() ?? "";

    // Strip quotes
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    if (!currentSection) {
      // Top-level keys
      if (key === "model") settings.model = value;
      if (key === "personality") settings.personality = value;
      if (key === "model_reasoning_effort")
        settings.modelReasoningEffort = value;
    } else if (currentSection === `projects."${cwd}"`) {
      // Project-specific keys
      if (key === "trust_level") settings.trustLevel = value;
    }
  }

  settings.mcpServerNames = Array.from(mcpServerNames);
  return settings;
}
