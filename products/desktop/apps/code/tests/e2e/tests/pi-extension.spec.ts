import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import type { PiExtensionEvent } from "@posthog/agent/pi/types";
import { expect, test } from "../fixtures/electron";

const EXTENSION_SOURCE = `
export default function (pi) {
  pi.registerCommand("extension-e2e", {
    description: "Exercise the PostHog Desktop extension RPC UI",
    handler: async (_args, ctx) => {
      ctx.ui.setTitle("Extension E2E");
      ctx.ui.setStatus("extension-e2e", "Extension ready");
      ctx.ui.setWidget("extension-e2e", ["Extension widget ready"]);
      const confirmed = await ctx.ui.confirm(
        "Extension confirmation",
        "Confirm the extension RPC round trip.",
      );
      ctx.ui.notify(
        confirmed ? "Extension E2E passed" : "Extension E2E cancelled",
        confirmed ? "info" : "warning",
      );
    },
  });
}
`;

const HOME_ENVIRONMENT_KEYS = [
  "APPDATA",
  "HOME",
  "LOCALAPPDATA",
  "USERPROFILE",
  "XDG_CONFIG_HOME",
] as const;

test.describe("Pi extensions", () => {
  test("loads a real extension and completes its UI round trip", async ({
    electronApp,
  }) => {
    const { e2eHome, resourcesPath } = await electronApp.evaluate(
      async ({ app }) => ({
        e2eHome: process.env.HOME ?? app.getPath("home"),
        resourcesPath: process.resourcesPath,
      }),
    );
    const rpcHostPath = path.join(
      resourcesPath,
      "app.asar.unpacked",
      ".vite",
      "build",
      "rpc-host.js",
    );
    expect(existsSync(rpcHostPath)).toBe(true);

    const extensionsDirectory = path.join(
      e2eHome,
      ".pi",
      "agent",
      "extensions",
    );
    await mkdir(extensionsDirectory, { recursive: true });
    await writeFile(
      path.join(extensionsDirectory, "extension-e2e.ts"),
      EXTENSION_SOURCE,
    );

    const previousEnvironment = new Map(
      HOME_ENVIRONMENT_KEYS.map((key) => [key, process.env[key]]),
    );
    for (const key of HOME_ENVIRONMENT_KEYS) {
      process.env[key] = e2eHome;
    }

    const events: PiExtensionEvent[] = [];
    let client: PiRpcClient | undefined;

    try {
      const { createPiRpcClient } = await import(
        "@posthog/agent/pi/rpc-client"
      );
      client = createPiRpcClient({
        cliPath: rpcHostPath,
        cwd: e2eHome,
        projectTrusted: false,
        providerOptions: { apiKey: "unused-e2e-key" },
      });
      client.onEvent((event) => {
        if (
          event.type === "extension_ui_request" ||
          event.type === "extension_error"
        ) {
          events.push(event);
        }
      });
      await client.start();

      const prompt = client.prompt("/extension-e2e");

      await expect
        .poll(() => events)
        .toContainEqual(
          expect.objectContaining({
            type: "extension_ui_request",
            method: "setTitle",
            title: "Extension E2E",
          }),
        );
      await expect
        .poll(() => events)
        .toContainEqual(
          expect.objectContaining({
            type: "extension_ui_request",
            method: "setStatus",
            statusKey: "extension-e2e",
            statusText: "Extension ready",
          }),
        );
      await expect
        .poll(() => events)
        .toContainEqual(
          expect.objectContaining({
            type: "extension_ui_request",
            method: "setWidget",
            widgetKey: "extension-e2e",
            widgetLines: ["Extension widget ready"],
          }),
        );
      await expect
        .poll(() => events)
        .toContainEqual(
          expect.objectContaining({
            type: "extension_ui_request",
            method: "confirm",
            title: "Extension confirmation",
            message: "Confirm the extension RPC round trip.",
          }),
        );

      const confirmation = events.find(
        (event) =>
          event.type === "extension_ui_request" && event.method === "confirm",
      );
      if (!confirmation) {
        throw new Error("Extension confirmation request was not emitted");
      }

      await client.respondToExtensionUI({
        type: "extension_ui_response",
        id: confirmation.id,
        confirmed: true,
      });
      await prompt;

      await expect
        .poll(() => events)
        .toContainEqual(
          expect.objectContaining({
            type: "extension_ui_request",
            method: "notify",
            message: "Extension E2E passed",
            notifyType: "info",
          }),
        );
    } finally {
      await client?.stop();
      for (const [key, value] of previousEnvironment) {
        if (value === undefined) {
          delete process.env[key];
        } else {
          process.env[key] = value;
        }
      }
    }
  });
});
