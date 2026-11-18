import { getGravatarRefresh } from "@posthog/core/auth/gravatarRefresh";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useGravatarRefreshStore } from "./gravatarRefreshStore";
import { useGravatarUrl } from "./useGravatarUrl";

function refreshGravatar(email: string, now: number): void {
  const { refreshedAtByEmail, setRefreshedAt } =
    useGravatarRefreshStore.getState();
  const refresh = getGravatarRefresh(email, refreshedAtByEmail, now);
  if (refresh) setRefreshedAt(refresh.email, refresh.refreshedAt);
}

async function gravatarUrl(email: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(email),
  );
  const hash = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `https://www.gravatar.com/avatar/${hash}?s=96&d=404`;
}

describe("useGravatarUrl", () => {
  afterEach(() => {
    act(() => useGravatarRefreshStore.setState({ refreshedAtByEmail: {} }));
  });

  it("keeps refreshed URLs after remount and updates all sizes for that email", async () => {
    const email = "refresh@example.com";
    const expected = await gravatarUrl(email);
    const profile = renderHook(() => useGravatarUrl(email, 144));
    const avatar = renderHook(() => useGravatarUrl(email));
    const other = renderHook(() => useGravatarUrl("other@example.com"));
    await waitFor(() => expect(profile.result.current).toBeDefined());
    await waitFor(() => expect(avatar.result.current).toBe(expected));
    await waitFor(() => expect(other.result.current).toBeDefined());
    const otherUrl = other.result.current;

    act(() => refreshGravatar(" REFRESH@Example.com ", 1000));
    const refreshedAt =
      useGravatarRefreshStore.getState().refreshedAtByEmail[email];
    expect(avatar.result.current).toBe(`${expected}&_=${refreshedAt}`);
    expect(profile.result.current).toBe(
      `${expected.replace("s=96", "s=144")}&_=${refreshedAt}`,
    );
    expect(other.result.current).toBe(otherUrl);
    const refreshedUrl = profile.result.current;
    profile.unmount();

    const reopened = renderHook(() => useGravatarUrl(email, 144));
    expect(reopened.result.current).toBe(refreshedUrl);

    act(() => refreshGravatar(email, 1000));
    expect(reopened.result.current).toBe(
      `${expected.replace("s=96", "s=144")}&_=1001`,
    );
  });

  it.each(["", "   "])("ignores an empty email (%j)", (email) => {
    expect(getGravatarRefresh(email, {}, 1000)).toBeUndefined();
  });

  it.each([
    { now: 999, expected: 1001 },
    { now: 1000, expected: 1001 },
    { now: 1002, expected: 1002 },
  ])("advances the refresh timestamp at $now", ({ now, expected }) => {
    const timestamps = { "refresh@example.com": 1000 };
    expect(
      getGravatarRefresh(" REFRESH@Example.com ", timestamps, now),
    ).toEqual({
      email: "refresh@example.com",
      refreshedAt: expected,
    });
    expect(timestamps).toEqual({ "refresh@example.com": 1000 });
  });

  it("returns undefined when there is no email", () => {
    const { result } = renderHook(() => useGravatarUrl(undefined));
    expect(result.current).toBeUndefined();
  });

  it.each([
    {
      name: "builds a SHA-256 Gravatar URL with the d=404 fallback",
      email: "user@example.com",
      size: undefined,
      expected:
        "https://www.gravatar.com/avatar/b4c9a289323b21a01c3e940f150eb9b8c542587f1abfd8f0e1cc1ffc5e475514?s=96&d=404",
    },
    {
      name: "lowercases and trims the email before hashing",
      email: "  TEST@Example.com ",
      size: undefined,
      expected:
        "https://www.gravatar.com/avatar/973dfe463ec85785f5f95af5ba3906eedb2d931c24e69824a89ea65dba4e813b?s=96&d=404",
    },
    {
      name: "requests the size the caller asks for",
      email: "user@example.com",
      size: 160,
      expected:
        "https://www.gravatar.com/avatar/b4c9a289323b21a01c3e940f150eb9b8c542587f1abfd8f0e1cc1ffc5e475514?s=160&d=404",
    },
  ])("$name", async ({ email, size, expected }) => {
    const { result } = renderHook(() => useGravatarUrl(email, size));
    await waitFor(() => expect(result.current).toBe(expected));
  });

  it("resolves synchronously on a later mount of an email hashed before", async () => {
    const expected = await gravatarUrl("remount@example.com");
    const first = renderHook(() => useGravatarUrl("remount@example.com"));
    await waitFor(() => expect(first.result.current).toBe(expected));
    first.unmount();

    const second = renderHook(() => useGravatarUrl("remount@example.com"));
    expect(second.result.current).toBe(expected);
  });

  it("never shows the previous person's URL while a changed email is hashing", async () => {
    const firstUrl = await gravatarUrl("first@example.com");
    const secondUrl = await gravatarUrl("second@example.com");
    const { result, rerender } = renderHook(
      ({ email }) => useGravatarUrl(email),
      { initialProps: { email: "first@example.com" } },
    );
    await waitFor(() => expect(result.current).toBe(firstUrl));

    rerender({ email: "second@example.com" });
    expect(result.current).not.toBe(firstUrl);

    await waitFor(() => expect(result.current).toBe(secondUrl));
  });
});
