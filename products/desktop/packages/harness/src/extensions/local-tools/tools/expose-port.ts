import { Socket } from "node:net";
import { networkInterfaces } from "node:os";
import { z } from "zod";
import { defineLocalTool, type LocalToolResult } from "../registry";
import {
  createSandboxPosthogClient,
  withReportDeadline,
} from "../signed-commit-artefacts";

export const EXPOSE_PORT_TOOL_NAME = "expose_port";

const RESERVED_PORTS = new Set([8080, 8181]);
const PROBE_TIMEOUT_MS = 2_000;

export const exposePortSchema = {
  port: z
    .number()
    .int()
    .min(1024)
    .max(65535)
    .refine((port) => !RESERVED_PORTS.has(port), {
      message: "This port is reserved for the sandbox.",
    })
    .describe("Port where the HTTP server listens inside this sandbox."),
  name: z
    .string()
    .trim()
    .min(1)
    .max(60)
    .optional()
    .describe(
      'Short name for the app, for example "Web app" or "Storybook". The user sees it beside the port.',
    ),
};

export type PortProbe = (host: string, port: number) => Promise<boolean>;

export function probePort(host: string, port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new Socket();
    const finish = (open: boolean) => {
      socket.destroy();
      resolve(open);
    };
    socket.setTimeout(PROBE_TIMEOUT_MS);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
    socket.connect(port, host);
  });
}

export function externalIPv4Address(): string | null {
  for (const addresses of Object.values(networkInterfaces())) {
    for (const address of addresses ?? []) {
      if (address.family === "IPv4" && !address.internal) {
        return address.address;
      }
    }
  }
  return null;
}

export async function checkListener(
  port: number,
  probe: PortProbe = probePort,
  externalAddress: string | null = externalIPv4Address(),
): Promise<string | null> {
  if (!(await probe("127.0.0.1", port))) {
    return `Nothing listens on port ${port}. Start the server first, then call ${EXPOSE_PORT_TOOL_NAME} again.`;
  }
  if (externalAddress && !(await probe(externalAddress, port))) {
    return `The server on port ${port} listens only on localhost, so the user cannot reach it. Restart it bound to 0.0.0.0 (for example --host 0.0.0.0), then call ${EXPOSE_PORT_TOOL_NAME} again.`;
  }
  return null;
}

export const exposePortTool = defineLocalTool({
  name: EXPOSE_PORT_TOOL_NAME,
  description:
    "Show a web server that runs in this sandbox to the user, in a browser tab inside PostHog Desktop. " +
    "Call this after you start a dev server, preview, or other HTTP app that the user should see or try. " +
    "Bind the server to 0.0.0.0, not localhost. Allow any Host header (for Vite, set server.allowedHosts to true), " +
    "because the user reaches the server through a proxy host. " +
    "Call it again with the same port to change the name.",
  schema: exposePortSchema,
  alwaysLoad: true,
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" && !!ctx.taskId && !!ctx.taskRunId,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    if (!ctx.taskId || !ctx.taskRunId) {
      return errorResult("Port preview is not available in this session.");
    }
    const client = createSandboxPosthogClient();
    if (!client) {
      return errorResult("PostHog is not configured in this sandbox.");
    }

    const listenerProblem = await checkListener(args.port);
    if (listenerProblem) {
      return errorResult(listenerProblem);
    }

    try {
      await withReportDeadline(
        (signal) =>
          client.exposeTaskRunPort(
            ctx.taskId as string,
            ctx.taskRunId as string,
            { port: args.port, name: args.name },
            signal,
          ),
        "port exposure",
      );
    } catch (error) {
      return errorResult(
        `Could not expose port ${args.port}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    const title = args.name
      ? `${args.name} (port ${args.port})`
      : `Port ${args.port}`;
    return {
      content: [
        {
          type: "text",
          text: `${title} is now available to the user as a preview in PostHog Desktop. Tell the user they can open it from the task header.`,
        },
      ],
    };
  },
});

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}
