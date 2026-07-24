import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OAuthEnv, OAuthHost } from "./identifiers";
import { OAuthService } from "./oauth";

const fetchMock = vi.fn();

function createDeps(env: Partial<OAuthEnv> = {}) {
  let callbackHandler:
    | ((path: string, searchParams: URLSearchParams) => boolean)
    | undefined;

  const deepLinkService = {
    registerHandler: vi.fn(
      (
        _name: string,
        handler: (path: string, searchParams: URLSearchParams) => boolean,
      ) => {
        callbackHandler = handler;
      },
    ),
    getProtocol: vi.fn(() => "posthog-code"),
  };

  const urlLauncher = { launch: vi.fn().mockResolvedValue(undefined) };

  const mainWindow = {
    isMinimized: vi.fn(() => false),
    restore: vi.fn(),
    focus: vi.fn(),
  };

  const host: OAuthHost = {
    waitForCode: vi.fn(),
    isDev: false,
    ...env,
  };

  const scopedLog = {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  const log = { ...scopedLog, scope: vi.fn(() => scopedLog) };

  const crypto = {
    randomBase64Url: vi.fn(() => "code-verifier"),
    sha256Base64Url: vi.fn(() => "code-challenge"),
  };

  const service = new OAuthService(
    deepLinkService as never,
    urlLauncher as never,
    mainWindow as never,
    host,
    log,
    crypto as never,
  );

  return {
    service,
    deepLinkService,
    urlLauncher,
    mainWindow,
    host,
    log,
    getCallbackHandler: () => callbackHandler,
  };
}

const TOKEN_RESPONSE = {
  access_token: "at",
  expires_in: 3600,
  token_type: "Bearer",
  scope: "",
  refresh_token: "rt",
};

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("OAuthService.refreshToken", () => {
  it("returns the token payload on success", async () => {
    const { service } = createDeps();
    fetchMock.mockResolvedValue(jsonResponse(TOKEN_RESPONSE));

    const result = await service.refreshToken("rt", "us");

    expect(result.success).toBe(true);
    expect(result.data).toEqual(TOKEN_RESPONSE);
  });

  it("maps 401 to an auth_error", async () => {
    const { service } = createDeps();
    fetchMock.mockResolvedValue(jsonResponse({}, 401));

    const result = await service.refreshToken("rt", "us");

    expect(result.success).toBe(false);
    expect(result.errorCode).toBe("auth_error");
  });

  it("maps 403 to an auth_error", async () => {
    const { service } = createDeps();
    fetchMock.mockResolvedValue(jsonResponse({}, 403));

    const result = await service.refreshToken("rt", "us");

    expect(result.errorCode).toBe("auth_error");
  });

  it.each([
    {
      name: "invalid_grant",
      body: { error: "invalid_grant" },
      expected: "auth_error",
    },
    {
      name: "invalid_token",
      body: { error: "invalid_token" },
      expected: "auth_error",
    },
    {
      name: "invalid_client",
      body: { error: "invalid_client" },
      expected: "unknown_error",
    },
    {
      name: "invalid_request",
      body: { error: "invalid_request" },
      expected: "unknown_error",
    },
    {
      name: "a non-string error field",
      body: { error: 42 },
      expected: "unknown_error",
    },
    { name: "no error field", body: {}, expected: "unknown_error" },
  ])("maps a 400 $name to a $expected", async ({ body, expected }) => {
    const { service } = createDeps();
    fetchMock.mockResolvedValue(jsonResponse(body, 400));

    const result = await service.refreshToken("rt", "us");

    expect(result.success).toBe(false);
    expect(result.errorCode).toBe(expected);
  });

  it("maps a 400 with an unparseable body to an unknown_error", async () => {
    const { service } = createDeps();
    fetchMock.mockResolvedValue(new Response("", { status: 400 }));

    const result = await service.refreshToken("rt", "us");

    expect(result.success).toBe(false);
    expect(result.errorCode).toBe("unknown_error");
  });

  it("maps 5xx to a server_error", async () => {
    const { service } = createDeps();
    fetchMock.mockResolvedValue(jsonResponse({}, 503));

    const result = await service.refreshToken("rt", "us");

    expect(result.errorCode).toBe("server_error");
  });

  it("maps other 4xx to an unknown_error", async () => {
    const { service } = createDeps();
    fetchMock.mockResolvedValue(jsonResponse({}, 404));

    const result = await service.refreshToken("rt", "us");

    expect(result.errorCode).toBe("unknown_error");
  });

  it("maps a thrown fetch to a network_error with a friendly message", async () => {
    const { service } = createDeps();
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));

    const result = await service.refreshToken("rt", "us");

    expect(result.errorCode).toBe("network_error");
    expect(result.error).toContain("internet connection");
  });
});

describe("OAuthService.cancelFlow", () => {
  it("succeeds when there is no pending flow", () => {
    const { service } = createDeps();
    expect(service.cancelFlow()).toEqual({ success: true });
  });
});

describe("OAuthService deep-link callback handler", () => {
  it("registers a callback handler on construction", () => {
    const { deepLinkService } = createDeps();
    expect(deepLinkService.registerHandler).toHaveBeenCalledWith(
      "callback",
      expect.any(Function),
    );
  });

  it("refocuses the window when a callback arrives with no in-app flow", () => {
    const { getCallbackHandler, mainWindow } = createDeps();
    mainWindow.isMinimized.mockReturnValue(true);

    const handled = getCallbackHandler()?.(
      "callback",
      new URLSearchParams("code=abc"),
    );

    expect(handled).toBe(true);
    expect(mainWindow.restore).toHaveBeenCalled();
    expect(mainWindow.focus).toHaveBeenCalled();
  });
});
