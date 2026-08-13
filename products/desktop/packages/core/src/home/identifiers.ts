// DI token for the Home work service. Lives in @posthog/core so the
// host-router router and the host DI container can both reference it without
// depending on where the concrete class is bound.
export const HOME_SERVICE = Symbol.for("posthog.core.home.service");
