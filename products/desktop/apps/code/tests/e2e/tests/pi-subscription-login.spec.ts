import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import type {
  PiRpcClient,
  PiRpcEvent,
  PiRpcProviderOptions,
} from "@posthog/agent/pi/rpc-client";
import { expect, test } from "../fixtures/electron";

const PROVIDER = "anthropic";
const ACCESS_TOKEN = "pi-byos-e2e-access-token";
const REFRESH_TOKEN = "pi-byos-e2e-refresh-token";
const AUTHORIZATION_CODE = "pi-byos-e2e-code";
const MODEL_ID = "claude-sonnet-4-5";
const RESPONSE_TEXT = "Pi BYOS E2E response";
const CALLBACK_URL = "http://127.0.0.1:53692/callback";
const REDIRECT_URI = "http://localhost:53692/callback";
const TOKEN_URL = "https://platform.claude.com/v1/oauth/token";

const HOME_ENVIRONMENT_KEYS = [
  "APPDATA",
  "HOME",
  "LOCALAPPDATA",
  "USERPROFILE",
  "XDG_CONFIG_HOME",
] as const;

const EXTENSION_SOURCE = `
import { writeFileSync } from "node:fs";
import { builtinProviders } from "__PI_PROVIDERS_PATH__";
import { fauxAssistantMessage, fauxProvider } from "__PI_FAUX_PATH__";

writeFileSync(__EXTENSION_MARKER_PATH__, "loaded");

export default function (pi) {
  const anthropic = builtinProviders().find((provider) => provider.id === "anthropic");
  if (!anthropic) {
    throw new Error("Anthropic provider is not available");
  }
  const faux = fauxProvider({
    provider: "anthropic",
    api: "anthropic-messages",
  });
  faux.setResponses([
    (_context, options) => {
      if (options?.apiKey !== "pi-byos-e2e-access-token") {
        throw new Error("Pi did not use the OAuth access token");
      }
      return fauxAssistantMessage("Pi BYOS E2E response");
    },
  ]);
  pi.registerProvider({
    ...anthropic,
    stream: faux.provider.stream,
    streamSimple: faux.provider.streamSimple,
  });
}
`;

function fetchPreloaderSource(capturePath: string): string {
  return `
import { appendFile } from "node:fs/promises";

const capturePath = ${JSON.stringify(capturePath)};
const tokenUrl = ${JSON.stringify(TOKEN_URL)};

globalThis.fetch = async (input, init) => {
  const request = new Request(input, init);
  if (request.method === "POST" && request.url === tokenUrl) {
    await appendFile(capturePath, (await request.text()) + "\\n");
    return new Response(
      JSON.stringify({
        access_token: ${JSON.stringify(ACCESS_TOKEN)},
        refresh_token: ${JSON.stringify(REFRESH_TOKEN)},
        expires_in: 3600,
      }),
      { headers: { "Content-Type": "application/json" } },
    );
  }
  throw new Error("Unexpected network request: " + request.method + " " + request.url);
};
`;
}

test.describe("Pi subscription login", () => {
  test("completes Anthropic OAuth through desktop IPC and uses the credential", async ({
    electronApp,
    window,
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

    const capturePath = path.join(e2eHome, "pi-byos-token-exchange.json");
    const preloaderPath = path.join(e2eHome, "pi-byos-fetch-preloader.mjs");
    const rpcHostWrapperPath = path.join(e2eHome, "pi-byos-rpc-host.mjs");
    const preloaderUrl = pathToFileURL(preloaderPath).href;
    await writeFile(preloaderPath, fetchPreloaderSource(capturePath));
    await writeFile(
      rpcHostWrapperPath,
      `import ${JSON.stringify(preloaderUrl)};\nimport ${JSON.stringify(pathToFileURL(rpcHostPath).href)};\n`,
    );

    let originalExecArgv: string[] | undefined;
    let loginStarted = false;

    const invoke = async <T>(
      type: "query" | "mutation",
      procedure: string,
      input: Record<string, string>,
    ): Promise<T> => {
      return window.evaluate(
        ({ type, procedure, input }) => {
          type TrpcResponse = {
            id?: string | number;
            error?: unknown;
            result?: { type?: string; data?: { json?: unknown } };
          };
          type TrpcBridge = {
            sendMessage: (message: unknown) => void;
            onMessage: (listener: (response: TrpcResponse) => void) => void;
          };
          type TrpcHelper = {
            invoke: (
              type: "query" | "mutation",
              procedure: string,
              input: Record<string, string>,
            ) => Promise<unknown>;
          };
          type TrpcWindow = typeof globalThis & {
            electronTRPC: TrpcBridge;
            piByosTrpcHelper?: TrpcHelper;
          };

          const trpcWindow = globalThis as TrpcWindow;
          trpcWindow.piByosTrpcHelper ??= (() => {
            const pending = new Map<
              string,
              {
                resolve: (value: unknown) => void;
                reject: (error: Error) => void;
              }
            >();
            trpcWindow.electronTRPC.onMessage((response) => {
              if (typeof response.id !== "string") {
                return;
              }
              const request = pending.get(response.id);
              if (!request) {
                return;
              }
              pending.delete(response.id);
              if (response.error) {
                request.reject(new Error(JSON.stringify(response.error)));
                return;
              }
              if (response.result?.type !== "data") {
                request.reject(new Error("tRPC operation did not return data"));
                return;
              }
              request.resolve(response.result.data?.json);
            });

            return {
              invoke(type, procedure, input) {
                const id = crypto.randomUUID();
                return new Promise((resolve, reject) => {
                  pending.set(id, { resolve, reject });
                  trpcWindow.electronTRPC.sendMessage({
                    method: "request",
                    operation: {
                      id,
                      type,
                      path: procedure,
                      input: { json: input },
                      context: {},
                    },
                  });
                });
              },
            };
          })();

          return trpcWindow.piByosTrpcHelper.invoke(type, procedure, input);
        },
        { type, procedure, input },
      ) as Promise<T>;
    };

    const subscriptionStatus = (): Promise<{ loginState: string }> =>
      invoke("query", "agent.piSubscriptionStatus", { provider: PROVIDER });
    const subscriptionMutation = (procedure: string): Promise<void> =>
      invoke("mutation", procedure, { provider: PROVIDER });

    try {
      await expect
        .poll(subscriptionStatus)
        .toEqual({ loginState: "logged-out" });

      originalExecArgv = await electronApp.evaluate(
        (_electron, preloaderUrl: string) => {
          const original = [...process.execArgv];
          process.execArgv.push(`--import=${preloaderUrl}`);
          return original;
        },
        preloaderUrl,
      );
      loginStarted = true;
      const login = await invoke<{ authUrl: string }>(
        "mutation",
        "agent.piSubscriptionLoginStart",
        { provider: PROVIDER },
      );
      const authorizationUrl = new URL(login.authUrl);
      expect(authorizationUrl.origin + authorizationUrl.pathname).toBe(
        "https://claude.ai/oauth/authorize",
      );
      expect(authorizationUrl.searchParams.get("response_type")).toBe("code");
      expect(authorizationUrl.searchParams.get("redirect_uri")).toBe(
        REDIRECT_URI,
      );
      expect(authorizationUrl.searchParams.get("code_challenge_method")).toBe(
        "S256",
      );

      const state = authorizationUrl.searchParams.get("state");
      const codeChallenge = authorizationUrl.searchParams.get("code_challenge");
      expect(state).toBeTruthy();
      expect(codeChallenge).toBeTruthy();
      if (!state || !codeChallenge) {
        throw new Error("OAuth URL was missing PKCE parameters");
      }
      expect(createHash("sha256").update(state).digest("base64url")).toBe(
        codeChallenge,
      );

      const callback = await fetch(
        `${CALLBACK_URL}?code=${AUTHORIZATION_CODE}&state=${encodeURIComponent(state)}`,
      );
      expect(callback.status).toBe(200);
      await expect
        .poll(subscriptionStatus)
        .toEqual({ loginState: "logged-in" });

      const exchanges = (await readFile(capturePath, "utf8"))
        .trim()
        .split("\n")
        .map((exchange) => JSON.parse(exchange) as Record<string, string>);
      expect(exchanges).toHaveLength(1);
      expect(exchanges[0]).toMatchObject({
        grant_type: "authorization_code",
        code: AUTHORIZATION_CODE,
        state,
        code_verifier: state,
        redirect_uri: REDIRECT_URI,
      });

      const workspace = path.join(e2eHome, "byos-workspace");
      const extensionsDirectory = path.join(workspace, ".pi", "extensions");
      await mkdir(extensionsDirectory, { recursive: true });
      const extensionMarkerPath = path.join(e2eHome, "pi-byos-extension");
      const piProviderPath = pathToFileURL(
        path.join(
          process.cwd(),
          "node_modules",
          "@earendil-works",
          "pi-ai",
          "dist",
          "providers",
          "all.js",
        ),
      ).href;
      const piFauxPath = pathToFileURL(
        path.join(
          process.cwd(),
          "node_modules",
          "@earendil-works",
          "pi-ai",
          "dist",
          "providers",
          "faux.js",
        ),
      ).href;
      await writeFile(
        path.join(extensionsDirectory, "pi-byos-e2e.ts"),
        EXTENSION_SOURCE.replace(
          "__EXTENSION_MARKER_PATH__",
          JSON.stringify(extensionMarkerPath),
        )
          .replace("__PI_PROVIDERS_PATH__", piProviderPath)
          .replace("__PI_FAUX_PATH__", piFauxPath),
      );

      const previousEnvironment = new Map(
        HOME_ENVIRONMENT_KEYS.map((key) => [key, process.env[key]]),
      );
      for (const key of HOME_ENVIRONMENT_KEYS) {
        process.env[key] = e2eHome;
      }

      const events: PiRpcEvent[] = [];
      let client: PiRpcClient | undefined;
      try {
        const { createPiRpcClient } = await import(
          "@posthog/agent/pi/rpc-client"
        );
        client = createPiRpcClient({
          cliPath: rpcHostWrapperPath,
          taskContext: {
            taskId: "pi-byos-e2e",
            cwd: workspace,
            projectId: 1,
            apiHost: "https://us.posthog.com",
            environment: "local",
          },
          providerOptions: {
            provider: PROVIDER,
          } satisfies PiRpcProviderOptions,
          model: MODEL_ID,
        });
        client.onEvent((event) => {
          events.push(event);
        });
        await client.start();
        await client.prompt("Respond using the Pi BYOS E2E provider.");
        await expect.poll(() => existsSync(extensionMarkerPath)).toBe(true);
        expect(
          events.filter((event) => event.type === "extension_error"),
        ).toEqual([]);

        await expect
          .poll(() =>
            events.filter(
              (event) =>
                event.type === "message_end" &&
                event.message.role === "assistant",
            ),
          )
          .toContainEqual(
            expect.objectContaining({
              message: expect.objectContaining({
                provider: PROVIDER,
                api: "anthropic-messages",
                model: MODEL_ID,
                content: [{ type: "text", text: RESPONSE_TEXT }],
              }),
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

      await subscriptionMutation("agent.piSubscriptionSignOut");
      await expect
        .poll(subscriptionStatus)
        .toEqual({ loginState: "logged-out" });
    } finally {
      if (loginStarted) {
        await subscriptionMutation("agent.piSubscriptionLoginCancel").catch(
          () => undefined,
        );
        await subscriptionMutation("agent.piSubscriptionSignOut").catch(
          () => undefined,
        );
      }
      if (originalExecArgv) {
        await electronApp.evaluate((_electron, execArgv: string[]) => {
          process.execArgv = execArgv;
        }, originalExecArgv);
      }
    }
  });
});
