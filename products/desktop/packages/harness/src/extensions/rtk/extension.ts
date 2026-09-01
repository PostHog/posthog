import { existsSync } from "node:fs";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type {
  BashToolCallEvent,
  ExtensionAPI,
  ExtensionFactory,
  ToolCallEvent,
} from "@earendil-works/pi-coding-agent";
import { rtkTarget } from "./targets.mjs";

const REWRITE_TIMEOUT_MS = 2_000;
const MIN_SUPPORTED_RTK_MINOR = 23;

export interface RtkExtensionOptions {
  rtkExecutable?: string;
}

export function resolveBundledRtkExecutable(): string | undefined {
  const target = rtkTarget() as string | undefined;
  if (!target) {
    return undefined;
  }

  const binary = process.platform === "win32" ? "rtk.exe" : "rtk";
  const directory = fileURLToPath(new URL(`./bin/${target}/`, import.meta.url));
  const executable = join(directory, binary);
  return existsSync(executable) ? executable : undefined;
}

function addRtkToPath(executable: string): void {
  if (executable === "rtk") {
    return;
  }

  const pathKey =
    process.env.PATH === undefined && process.env.Path ? "Path" : "PATH";
  const directory = dirname(executable);
  const directories = (process.env[pathKey] ?? "").split(delimiter);
  if (directories.includes(directory)) {
    return;
  }

  process.env[pathKey] = [directory, ...directories]
    .filter(Boolean)
    .join(delimiter);
}

function isBashToolCallEvent(event: ToolCallEvent): event is BashToolCallEvent {
  return event.toolName === "bash";
}

function parseSemver(raw: string): [number, number, number] | null {
  const match = raw.trim().match(/(\d+)\.(\d+)\.(\d+)/);
  if (!match) {
    return null;
  }

  return [
    Number.parseInt(match[1], 10),
    Number.parseInt(match[2], 10),
    Number.parseInt(match[3], 10),
  ];
}

async function rewriteCommand(
  pi: ExtensionAPI,
  executable: string,
  command: string,
  signal?: AbortSignal,
): Promise<string | null> {
  const result = await pi.exec(executable, ["rewrite", command], {
    timeout: REWRITE_TIMEOUT_MS,
    signal,
  });
  if (result.killed || (result.code !== 0 && result.code !== 3)) {
    return null;
  }

  return result.stdout.trim() || null;
}

export function createRtkExtension(
  options: RtkExtensionOptions = {},
): ExtensionFactory {
  return async (pi: ExtensionAPI) => {
    if (process.env.RTK_DISABLED === "1" || process.env.POSTHOG_RTK === "0") {
      return;
    }

    const executable =
      options.rtkExecutable ?? resolveBundledRtkExecutable() ?? "rtk";
    addRtkToPath(executable);
    const version = await pi.exec(executable, ["--version"], {
      timeout: REWRITE_TIMEOUT_MS,
    });
    if (version.code !== 0) {
      return;
    }

    const parsedVersion = parseSemver(version.stdout.replace(/^rtk\s+/, ""));
    if (
      parsedVersion &&
      parsedVersion[0] === 0 &&
      parsedVersion[1] < MIN_SUPPORTED_RTK_MINOR
    ) {
      return;
    }

    pi.on("tool_call", async (event, context) => {
      if (!isBashToolCallEvent(event)) {
        return;
      }

      const command = event.input.command;
      if (
        typeof command !== "string" ||
        command.trim() === "" ||
        command.startsWith("rtk ") ||
        process.env.RTK_DISABLED === "1"
      ) {
        return;
      }

      try {
        const rewritten = await rewriteCommand(
          pi,
          executable,
          command,
          context.signal,
        );
        if (rewritten && rewritten !== command) {
          event.input.command = rewritten;
        }
      } catch {
        return;
      }
    });
  };
}

export default function rtk(pi: ExtensionAPI): void | Promise<void> {
  return createRtkExtension()(pi);
}
