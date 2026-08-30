import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useGravatarUrl } from "./useGravatarUrl";

describe("useGravatarUrl", () => {
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

  it("clears the previous URL while a changed email is hashing", async () => {
    const { result, rerender } = renderHook(
      ({ email }) => useGravatarUrl(email),
      { initialProps: { email: "user@example.com" } },
    );
    await waitFor(() =>
      expect(result.current).toContain(
        "b4c9a289323b21a01c3e940f150eb9b8c542587f1abfd8f0e1cc1ffc5e475514",
      ),
    );

    rerender({ email: "test@example.com" });
    // The prior person's URL must not linger during the new hash.
    expect(result.current).toBeUndefined();

    await waitFor(() =>
      expect(result.current).toContain(
        "973dfe463ec85785f5f95af5ba3906eedb2d931c24e69824a89ea65dba4e813b",
      ),
    );
  });
});
