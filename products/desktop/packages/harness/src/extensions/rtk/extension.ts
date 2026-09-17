import type {
  BashToolCallEvent,
  ExtensionAPI,
  ExtensionFactory,
  ToolCallEvent,
} from "@earendil-works/pi-coding-agent";

const REWRITE_TIMEOUT_MS = 2_000;
const MIN_SUPPORTED_RTK_MINOR = 23;

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
  command: string,
  signal?: AbortSignal,
): Promise<string | null> {
  const result = await pi.exec("rtk", ["rewrite", command], {
    timeout: REWRITE_TIMEOUT_MS,
    signal,
  });
  if (result.killed || (result.code !== 0 && result.code !== 3)) {
    return null;
  }

  return result.stdout.trim() || null;
}

export function createRtkExtension(): ExtensionFactory {
  return async (pi: ExtensionAPI) => {
    if (process.env.POSTHOG_RTK !== "1") {
      return;
    }

    const version = await pi.exec("rtk", ["--version"], {
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
        command.startsWith("rtk ")
      ) {
        return;
      }

      try {
        const rewritten = await rewriteCommand(pi, command, context.signal);
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
