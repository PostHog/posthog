// The desktop app registers a different custom scheme per build: production
// installs use `posthog-code://`, local dev builds use `posthog-code-dev://`.
// A dev frontend (./bin/start) is exactly when you're testing against a dev
// desktop build, so target that scheme there. Build-time constant, so it never
// flips after mount and double-fires.
export const DESKTOP_SCHEME = process.env.NODE_ENV === 'development' ? 'posthog-code-dev' : 'posthog-code'
