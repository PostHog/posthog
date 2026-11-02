import { beforeEach, describe, expect, it, vi } from "vitest";

const secureStore = vi.hoisted(() => ({
  deleteItemAsync: vi.fn(),
  getItemAsync: vi.fn(),
  setItemAsync: vi.fn(),
}));

vi.mock("expo/fetch", () => ({ fetch: vi.fn() }));
vi.mock("expo-secure-store", () => secureStore);
vi.mock("expo-auth-session", () => ({}));
vi.mock("expo-web-browser", () => ({ maybeCompleteAuthSession: vi.fn() }));

import { type Session, useAuth } from "./auth";

const savedSession: Session = {
  region: "us",
  host: "https://us.posthog.com",
  apiKey: "old-access-token",
  refreshToken: "old-refresh-token",
  expiresAt: Date.now() + 60_000,
  scopedTeams: [42],
  projectId: 42,
  projectName: "Demo project",
  userId: 7,
  userName: "Pat",
};

describe("mobilehog auth", () => {
  beforeEach(() => {
    secureStore.deleteItemAsync.mockReset();
    secureStore.getItemAsync.mockReset();
    secureStore.setItemAsync.mockReset();
    useAuth.setState({ session: null, hydrated: false, generation: 0 });
  });

  it("forces an existing OAuth session to reauthorize after scopes change", async () => {
    secureStore.getItemAsync.mockResolvedValue(JSON.stringify(savedSession));

    await useAuth.getState().hydrate();

    expect(secureStore.deleteItemAsync).toHaveBeenCalledWith(
      "mobilehog_session",
    );
    expect(useAuth.getState()).toMatchObject({
      session: null,
      hydrated: true,
    });
  });
});
