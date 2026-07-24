import { spawn } from "node:child_process";
import http from "node:http";
import {
  getCloudUrlFromRegion,
  getOauthClientIdFromRegion,
  OAUTH_SCOPES,
} from "@posthog/shared";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  type MockInstance,
  vi,
} from "vitest";
import {
  buildAuthorizeUrl,
  getCallbackPort,
  getRedirectUri,
  loginPosthog,
  refreshPosthog,
} from "./oauth";

vi.mock("node:child_process", async () => {
  const actual =
    await vi.importActual<typeof import("node:child_process")>(
      "node:child_process",
    );
  return {
    ...actual,
    spawn: vi.fn(() => ({ unref: vi.fn() })),
  };
});

function fakeCallbacks(
  overrides: Partial<{
    signal: AbortSignal;
  }> = {},
) {
  return {
    onAuth: vi.fn(),
    onDeviceCode: vi.fn(),
    onPrompt: vi.fn(),
    onSelect: vi.fn(),
    ...overrides,
  };
}

function hitPath(port: number, path: string): Promise<void> {
  return new Promise((resolve) => {
    const req = http.get({ host: "localhost", port, path }, (res) => {
      res.resume();
      res.on("end", resolve);
    });
    req.on("error", () => resolve());
  });
}

function hitCallback(port: number, query: string): Promise<void> {
  return hitPath(port, `/callback${query}`);
}

function hitCallbackBody(port: number, query: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const req = http.get(
      { host: "localhost", port, path: `/callback${query}` },
      (res) => {
        let body = "";
        res.on("data", (chunk) => {
          body += chunk;
        });
        res.on("end", () => resolve(body));
      },
    );
    req.on("error", reject);
  });
}

async function getAvailablePort(): Promise<number> {
  const server = http.createServer();

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });

  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("Failed to allocate an OAuth callback port");
  }

  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });

  return address.port;
}

describe("buildAuthorizeUrl", () => {
  it("targets the same authorize endpoint and client as the desktop app", () => {
    const url = buildAuthorizeUrl("us", "challenge123", getRedirectUri(8237));

    expect(url.origin + url.pathname).toBe(
      `${getCloudUrlFromRegion("us")}/oauth/authorize`,
    );
    expect(url.searchParams.get("client_id")).toBe(
      getOauthClientIdFromRegion("us"),
    );
  });

  it("uses PKCE S256 and the desktop app scope + access level", () => {
    const url = buildAuthorizeUrl("eu", "challenge123", getRedirectUri());

    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("code_challenge")).toBe("challenge123");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("scope")).toBe(OAUTH_SCOPES.join(" "));
    expect(url.searchParams.get("required_access_level")).toBe("project");
  });

  it("routes each region to its own cloud host", () => {
    for (const region of ["us", "eu", "dev"] as const) {
      const url = buildAuthorizeUrl(region, "c", getRedirectUri());
      expect(url.origin).toBe(new URL(getCloudUrlFromRegion(region)).origin);
      expect(url.searchParams.get("client_id")).toBe(
        getOauthClientIdFromRegion(region),
      );
    }
  });
});

describe("getRedirectUri", () => {
  it("is a loopback callback the CLI can capture", () => {
    expect(getRedirectUri(8237)).toBe("http://localhost:8237/callback");
  });
});

describe("getCallbackPort", () => {
  const originalPort = process.env.HARNESS_OAUTH_PORT;

  afterEach(() => {
    if (originalPort === undefined) {
      delete process.env.HARNESS_OAUTH_PORT;
    } else {
      process.env.HARNESS_OAUTH_PORT = originalPort;
    }
  });

  it("defaults to 8237 when unset", () => {
    delete process.env.HARNESS_OAUTH_PORT;
    expect(getCallbackPort()).toBe(8237);
  });

  it("uses a valid HARNESS_OAUTH_PORT override", () => {
    process.env.HARNESS_OAUTH_PORT = "9999";
    expect(getCallbackPort()).toBe(9999);
  });

  it.each(["not-a-number", "0", "-5", ""])(
    "falls back to the default for invalid value %j",
    (value) => {
      process.env.HARNESS_OAUTH_PORT = value;
      expect(getCallbackPort()).toBe(8237);
    },
  );
});

describe("loginPosthog region selection", () => {
  const originalPort = process.env.HARNESS_OAUTH_PORT;
  let fetchSpy: MockInstance<typeof fetch>;
  let port: number;

  beforeEach(async () => {
    port = await getAvailablePort();
    process.env.HARNESS_OAUTH_PORT = String(port);
    fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "access-1",
        refresh_token: "refresh-1",
        expires_in: 3600,
        token_type: "Bearer",
      }),
    } as Response);
  });

  afterEach(() => {
    if (originalPort === undefined) {
      delete process.env.HARNESS_OAUTH_PORT;
    } else {
      process.env.HARNESS_OAUTH_PORT = originalPort;
    }
    fetchSpy.mockRestore();
  });

  it("uses the explicit region directly and never prompts", async () => {
    const callbacks = fakeCallbacks();
    const loginPromise = loginPosthog(callbacks, "eu");

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const authUrl = (callbacks.onAuth.mock.calls[0]?.[0] as { url: string })
      .url;
    const state = new URL(authUrl).searchParams.get("state") ?? "";

    expect(callbacks.onSelect).not.toHaveBeenCalled();
    expect(new URL(authUrl).origin).toBe(
      new URL(getCloudUrlFromRegion("eu")).origin,
    );

    await hitCallback(port, `?code=abc123&state=${state}`);
    const credentials = await loginPromise;
    expect(credentials.region).toBe("eu");
  });

  it("prompts for a region with US/EU options when none is explicit", async () => {
    const callbacks = fakeCallbacks();
    callbacks.onSelect.mockResolvedValue("eu");

    const loginPromise = loginPosthog(callbacks);

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const authUrl = (callbacks.onAuth.mock.calls[0]?.[0] as { url: string })
      .url;
    const state = new URL(authUrl).searchParams.get("state") ?? "";

    expect(callbacks.onSelect).toHaveBeenCalledWith({
      message: "Select your PostHog region",
      options: [
        { id: "us", label: "United States" },
        { id: "eu", label: "European Union" },
      ],
    });
    expect(new URL(authUrl).origin).toBe(
      new URL(getCloudUrlFromRegion("eu")).origin,
    );

    await hitCallback(port, `?code=abc123&state=${state}`);
    const credentials = await loginPromise;
    expect(credentials.region).toBe("eu");
  });

  it("does not offer dev as an interactive region option", async () => {
    const callbacks = fakeCallbacks();
    callbacks.onSelect.mockResolvedValue("us");

    const loginPromise = loginPosthog(callbacks);
    await vi.waitFor(() => expect(callbacks.onSelect).toHaveBeenCalled());

    const options = callbacks.onSelect.mock.calls[0]?.[0]?.options as {
      id: string;
    }[];
    expect(options.map((option) => option.id)).toEqual(["us", "eu"]);

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const authUrl = (callbacks.onAuth.mock.calls[0]?.[0] as { url: string })
      .url;
    const state = new URL(authUrl).searchParams.get("state") ?? "";
    await hitCallback(port, `?code=abc123&state=${state}`);
    await loginPromise;
  });

  it("rejects when region selection is cancelled", async () => {
    const callbacks = fakeCallbacks();
    callbacks.onSelect.mockResolvedValue(undefined);

    await expect(loginPosthog(callbacks)).rejects.toThrow(
      /region selection cancelled/,
    );
    expect(callbacks.onAuth).not.toHaveBeenCalled();
  });
});

describe("loginPosthog", { timeout: 15_000 }, () => {
  const originalPort = process.env.HARNESS_OAUTH_PORT;
  let fetchSpy: MockInstance<typeof fetch>;
  let port: number;

  beforeEach(async () => {
    port = await getAvailablePort();
    process.env.HARNESS_OAUTH_PORT = String(port);
    fetchSpy = vi.spyOn(global, "fetch");
  });

  afterEach(() => {
    if (originalPort === undefined) {
      delete process.env.HARNESS_OAUTH_PORT;
    } else {
      process.env.HARNESS_OAUTH_PORT = originalPort;
    }
    fetchSpy.mockRestore();
    vi.mocked(spawn).mockClear();
  });

  it("ignores requests to unrelated paths and still resolves on the real callback", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "access-1",
        refresh_token: "refresh-1",
        expires_in: 3600,
        token_type: "Bearer",
      }),
    } as Response);

    const callbacks = fakeCallbacks();
    const loginPromise = loginPosthog(callbacks, "us");

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const authUrl = (callbacks.onAuth.mock.calls[0]?.[0] as { url: string })
      .url;
    const state = new URL(authUrl).searchParams.get("state") ?? "";

    await hitPath(port, "/unrelated");
    await hitCallback(port, `?code=abc123&state=${state}`);

    const credentials = await loginPromise;
    expect(credentials.access).toBe("access-1");
  });

  it("rejects with a timeout error when no callback arrives in time", async () => {
    vi.useFakeTimers();
    try {
      let resolveListening: () => void = () => {};
      const listening = new Promise<void>((resolve) => {
        resolveListening = resolve;
      });
      const callbacks = fakeCallbacks();
      callbacks.onAuth.mockImplementation(() => resolveListening());

      const loginPromise = loginPosthog(callbacks, "us");
      const assertion = expect(loginPromise).rejects.toThrow(/timed out/);

      await listening;
      await vi.advanceTimersByTimeAsync(180_000);

      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects when the callback server fails to start", async () => {
    const blocker = http.createServer();
    await new Promise<void>((resolve) => {
      blocker.listen(port, "127.0.0.1", resolve);
    });
    try {
      const callbacks = fakeCallbacks();
      await expect(loginPosthog(callbacks, "us")).rejects.toThrow();
    } finally {
      await new Promise<void>((resolve) => blocker.close(() => resolve()));
    }
  });

  it("opens the browser, captures the callback code, and exchanges it for credentials", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "access-1",
        refresh_token: "refresh-1",
        expires_in: 3600,
        token_type: "Bearer",
      }),
    } as Response);

    const callbacks = fakeCallbacks();
    let authUrl = "";
    callbacks.onAuth.mockImplementation((info: { url: string }) => {
      authUrl = info.url;
    });

    const loginPromise = loginPosthog(callbacks, "us");

    await vi.waitFor(() => {
      expect(callbacks.onAuth).toHaveBeenCalled();
    });
    expect(spawn).toHaveBeenCalled();

    const state = new URL(authUrl).searchParams.get("state") ?? "";
    const body = await hitCallbackBody(port, `?code=abc123&state=${state}`);
    expect(body).toContain("Authentication complete");

    const credentials = await loginPromise;
    expect(credentials.access).toBe("access-1");
    expect(credentials.refresh).toBe("refresh-1");
    expect(credentials.region).toBe("us");
    expect(credentials.expires).toBeGreaterThan(Date.now());

    expect(fetchSpy).toHaveBeenCalledWith(
      `${getCloudUrlFromRegion("us")}/oauth/token`,
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"grant_type":"authorization_code"'),
      }),
    );
  });

  it("rejects when the callback reports an OAuth error, and serves the failure page, not the success page", async () => {
    const callbacks = fakeCallbacks();
    const loginPromise = loginPosthog(callbacks, "us");
    const assertion =
      expect(loginPromise).rejects.toThrow(/PostHog OAuth error/);

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const body = await hitCallbackBody(port, "?error=access_denied");
    expect(body).toContain("Authentication failed");
    expect(body).not.toContain("Authentication complete");

    await assertion;
  });

  it("rejects when the callback is missing a code, and serves the failure page", async () => {
    const callbacks = fakeCallbacks();
    const loginPromise = loginPosthog(callbacks, "us");
    const assertion = expect(loginPromise).rejects.toThrow(/missing code/);

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const body = await hitCallbackBody(port, "?state=whatever");
    expect(body).toContain("Authentication failed");
    expect(body).not.toContain("Authentication complete");

    await assertion;
  });

  it("rejects on a state mismatch, and serves the failure page", async () => {
    const callbacks = fakeCallbacks();
    const loginPromise = loginPosthog(callbacks, "us");
    const assertion = expect(loginPromise).rejects.toThrow(/state mismatch/);

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const body = await hitCallbackBody(port, "?code=abc123&state=wrong-state");
    expect(body).toContain("Authentication failed");
    expect(body).not.toContain("Authentication complete");

    await assertion;
  });

  it("rejects when the abort signal fires before the callback arrives", async () => {
    const controller = new AbortController();
    const callbacks = fakeCallbacks({ signal: controller.signal });

    const loginPromise = loginPosthog(callbacks, "us");
    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());

    controller.abort();

    await expect(loginPromise).rejects.toThrow(/cancelled/);
  });

  it("rejects immediately when the signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const callbacks = fakeCallbacks({ signal: controller.signal });

    await expect(loginPosthog(callbacks, "us")).rejects.toThrow(/cancelled/);
  });

  it("surfaces token endpoint failures with response detail", async () => {
    fetchSpy.mockResolvedValue({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      text: async () => "invalid_grant",
    } as Response);

    const callbacks = fakeCallbacks();
    const loginPromise = loginPosthog(callbacks, "us");
    const assertion = expect(loginPromise).rejects.toThrow(
      /PostHog token request failed: 400 Bad Request invalid_grant/,
    );

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const authUrl = (callbacks.onAuth.mock.calls[0]?.[0] as { url: string })
      .url;
    const state = new URL(authUrl).searchParams.get("state") ?? "";
    await hitCallback(port, `?code=abc123&state=${state}`);

    await assertion;
  });
});

describe("openBrowser (via loginPosthog)", () => {
  const originalPort = process.env.HARNESS_OAUTH_PORT;
  const originalPlatform = process.platform;
  let fetchSpy: MockInstance<typeof fetch>;
  let port: number;

  beforeEach(async () => {
    port = await getAvailablePort();
    process.env.HARNESS_OAUTH_PORT = String(port);
    fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "a",
        refresh_token: "r",
        expires_in: 3600,
        token_type: "Bearer",
      }),
    } as Response);
  });

  afterEach(() => {
    if (originalPort === undefined) {
      delete process.env.HARNESS_OAUTH_PORT;
    } else {
      process.env.HARNESS_OAUTH_PORT = originalPort;
    }
    fetchSpy.mockRestore();
    vi.mocked(spawn).mockClear();
    Object.defineProperty(process, "platform", { value: originalPlatform });
  });

  it.each([
    ["darwin", "open"],
    ["win32", "cmd"],
    ["linux", "xdg-open"],
  ] as const)(
    "uses the right opener command on %s",
    async (platform, command) => {
      Object.defineProperty(process, "platform", { value: platform });

      const callbacks = fakeCallbacks();
      const loginPromise = loginPosthog(callbacks, "us");

      await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
      const authUrl = (callbacks.onAuth.mock.calls[0]?.[0] as { url: string })
        .url;
      const state = new URL(authUrl).searchParams.get("state") ?? "";

      expect(spawn).toHaveBeenCalledWith(
        command,
        expect.any(Array),
        expect.objectContaining({ stdio: "ignore", detached: true }),
      );

      await hitCallback(port, `?code=abc123&state=${state}`);
      await loginPromise;
    },
  );

  it("swallows errors thrown while spawning the opener", async () => {
    vi.mocked(spawn).mockImplementationOnce(() => {
      throw new Error("spawn failed");
    });

    const callbacks = fakeCallbacks();
    const loginPromise = loginPosthog(callbacks, "us");

    await vi.waitFor(() => expect(callbacks.onAuth).toHaveBeenCalled());
    const authUrl = (callbacks.onAuth.mock.calls[0]?.[0] as { url: string })
      .url;
    const state = new URL(authUrl).searchParams.get("state") ?? "";

    await hitCallback(port, `?code=abc123&state=${state}`);
    await expect(loginPromise).resolves.toBeDefined();
  });
});

describe("refreshPosthog", () => {
  let fetchSpy: MockInstance<typeof fetch>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("exchanges a refresh token for new credentials on the same region", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "new-access",
        refresh_token: "new-refresh",
        expires_in: 7200,
        token_type: "Bearer",
      }),
    } as Response);

    const credentials = await refreshPosthog("us", {
      access: "old-access",
      refresh: "old-refresh",
      expires: 0,
    });

    expect(credentials.access).toBe("new-access");
    expect(credentials.refresh).toBe("new-refresh");
    expect(credentials.region).toBe("us");
    expect(fetchSpy).toHaveBeenCalledWith(
      `${getCloudUrlFromRegion("us")}/oauth/token`,
      expect.objectContaining({
        body: expect.stringContaining('"grant_type":"refresh_token"'),
      }),
    );
  });

  it("prefers the region embedded in the stored credentials over the passed-in default", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "new-access",
        refresh_token: "new-refresh",
        expires_in: 7200,
        token_type: "Bearer",
      }),
    } as Response);

    const credentials = await refreshPosthog("us", {
      access: "old-access",
      refresh: "old-refresh",
      expires: 0,
      region: "eu",
    });

    expect(credentials.region).toBe("eu");
    expect(fetchSpy).toHaveBeenCalledWith(
      `${getCloudUrlFromRegion("eu")}/oauth/token`,
      expect.objectContaining({
        body: expect.stringContaining(
          `"client_id":"${getOauthClientIdFromRegion("eu")}"`,
        ),
      }),
    );
  });

  it("throws when the refresh request fails", async () => {
    fetchSpy.mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      text: async () => "expired",
    } as Response);

    await expect(
      refreshPosthog("us", {
        access: "old-access",
        refresh: "old-refresh",
        expires: 0,
      }),
    ).rejects.toThrow(/PostHog token request failed: 401 Unauthorized expired/);
  });
});
