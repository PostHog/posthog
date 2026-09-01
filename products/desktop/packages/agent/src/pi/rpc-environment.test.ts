import { describe, expect, it } from "vitest";
import { safePiEnvironment } from "./rpc-environment";

describe("safePiEnvironment", () => {
  it("retains explicitly selected user variables without exposing server credentials", () => {
    expect(
      safePiEnvironment(
        {
          PATH: "/usr/bin",
          IS_SANDBOX: "1",
          BASH_ENV: "/tmp/managed-bash-env.sh",
          PACKAGE_REGISTRY_TOKEN: "example-user-value",
          POSTHOG_PERSONAL_API_KEY: "example-server-value",
        },
        ["PACKAGE_REGISTRY_TOKEN"],
      ),
    ).toEqual({
      PATH: "/usr/bin",
      IS_SANDBOX: "1",
      BASH_ENV: "/tmp/managed-bash-env.sh",
      PACKAGE_REGISTRY_TOKEN: "example-user-value",
    });
  });
});
