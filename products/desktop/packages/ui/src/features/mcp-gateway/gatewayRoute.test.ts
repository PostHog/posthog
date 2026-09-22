import { describe, expect, it } from "vitest";
import { type GatewayRoute, isRouteAllowed } from "./gatewayRoute";

describe("isRouteAllowed", () => {
  // The route guard is what actually keeps a member on or off a view, since
  // the rail only hides links. Audit must stay member-reachable; the admin
  // views must not become so.
  it.each([
    [{ view: "servers" }, true],
    [{ view: "audit" }, true],
    [{ view: "team" }, false],
    [{ view: "agent", accountId: "sa-1" }, false],
    [{ view: "member", userId: 1 }, false],
    [{ view: "settings" }, false],
  ] as [GatewayRoute, boolean][])(
    "member access to %o is %s",
    (route, allowed) => {
      expect(
        isRouteAllowed(route, { isAdmin: false, canAddServers: false }),
      ).toBe(allowed);
    },
  );
});
