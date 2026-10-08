import posthog, {
    BeforeSendFn,
    BrowserMetricsConfig,
    PostHogConfig,
    SessionRecordingOptions,
} from "posthog-js";

import { FEATURE_FLAGS } from "lib/constants";
import { isOAuthMode } from "lib/oauth/oauthClient";
import { inStorybook, inStorybookTestRunner } from "lib/utils/dom";
import { isEmbeddedPageFrame } from "lib/utils/embeddedPageFrame";
import { getAppContext, isHobbyDeployment } from "lib/utils/getAppContext";

import { startDetachedElementTracking } from "./detachedElementTracker";

export const SDK_DEFAULTS_DATE = "2026-05-30";

// The same hash as posthog-js's own `sampleOnProperty`, so existing sessions keep their side of the
// split. Inlined because the deep import of that extension ships a second copy of @posthog/core.
export function isInDeferredInitSample(sessionId: string): boolean {
    let hash = 0;
    for (let i = 0; i < sessionId.length; i++) {
        hash = (hash << 5) - hash + sessionId.charCodeAt(i);
        hash |= 0;
    }
    return Math.abs(hash) % 100 < 50;
}

const LAST_SEEN_FEATURE_FLAGS_KEY = "posthog-app-last-seen-feature-flags";

export interface LastSeenFeatureFlags {
    distinctId: string;
    featureFlags: Record<string, boolean | string>;
}

export interface LoadPostHogJSOptions {
    /**
     * Hook posthog-js's `before_send` so the caller can mutate or drop events before they leave
     * the browser. Used to redact the SharingConfiguration access token from URL-shaped properties:
     * the interview share page in `frontend/src/exporter/index.tsx`, and every main-app page in
     * `frontend/src/scenes/bootApp.ts`.
     */
    beforeSend?: BeforeSendFn | BeforeSendFn[];
    /**
     * Extra `session_recording` config merged on top of the defaults — useful for overriding URL
     * / network-payload masking when the page renders sensitive bearer tokens in its own URL.
     */
    sessionRecording?: Partial<SessionRecordingOptions>;
    /**
     * Extra `metrics` config merged on top of the defaults. `before_send` and
     * `maskCapturedNetworkRequestFn` do not cover the network metrics channel, so the exporter
     * app uses this to override `network.attributes` and keep the SharingConfiguration access
     * token out of the captured `path`. See `frontend/src/exporter/index.tsx`.
     */
    metrics?: Partial<BrowserMetricsConfig>;
}

type UserIdentityWithFlags = NonNullable<
    Window["POSTHOG_USER_IDENTITY_WITH_FLAGS"]
>;

/**
 * The Django bootstrap leaves out every flag it cannot evaluate locally, for example a flag whose
 * cohort reads a person property that Django does not send. posthog-js treats a flag that is not in
 * the bootstrap as off until /flags responds, so the first render drops those flags and then shows
 * them again. This fills only the missing keys from the last flags this same user saw, so server
 * values still win and a different user on the same browser never gets them.
 *
 * `distinctId` is the user Django evaluated the bootstrap for. The bootstrap itself carries no
 * distinct ID, so it cannot identify the user.
 */
export function withLastSeenFeatureFlags(
    bootstrap: UserIdentityWithFlags,
    lastSeen: LastSeenFeatureFlags | null,
    distinctId: string | undefined,
): NonNullable<PostHogConfig["bootstrap"]> {
    if (!bootstrap.featureFlags) {
        return { ...bootstrap, featureFlags: undefined };
    }
    // An empty bootstrap makes posthog-js use its own persisted flags, which are already complete.
    if (
        !lastSeen ||
        !distinctId ||
        lastSeen.distinctId !== distinctId ||
        !Object.keys(bootstrap.featureFlags).length
    ) {
        return bootstrap;
    }
    return {
        ...bootstrap,
        featureFlags: { ...lastSeen.featureFlags, ...bootstrap.featureFlags },
    };
}

// pinned: analytics property name. Insights filter the framed pages by it.
const stampEmbeddedPageFrame: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: { ...event.properties, embedded_page_frame: true },
    };

function readLastSeenFeatureFlags(): LastSeenFeatureFlags | null {
    try {
        const stored = window.localStorage.getItem(LAST_SEEN_FEATURE_FLAGS_KEY);
        return stored ? JSON.parse(stored) : null;
    } catch {
        return null;
    }
}

function writeLastSeenFeatureFlags(lastSeen: LastSeenFeatureFlags): void {
    try {
        window.localStorage.setItem(
            LAST_SEEN_FEATURE_FLAGS_KEY,
            JSON.stringify(lastSeen),
        );
    } catch {
        // Storage can be full or blocked. The cache only smooths the first render, so skip it.
    }
}

export function loadPostHogJS(options: LoadPostHogJSOptions = {}): void {
    if (window.JS_POSTHOG_API_KEY) {
        posthog.init(window.JS_POSTHOG_API_KEY, {
            opt_out_useragent_filter: window.location.hostname === "localhost", // we ARE a bot when running in localhost, so we need to enable this opt-out
            api_host: window.JS_POSTHOG_HOST,
            ui_host: window.JS_POSTHOG_UI_HOST,
            defaults: SDK_DEFAULTS_DATE,
            // Hobby static files use /static/<asset>.js, without a version directory.
            ...(isHobbyDeployment() && window.JS_POSTHOG_SELF_CAPTURE
                ? { strict_script_versioning: false as const }
                : {}),
            persistence: "localStorage+cookie",
            cookie_persisted_properties: [
                "prod_interest", // posthog.com sets these based on what docs were browsed
            ],
            bootstrap: window.POSTHOG_USER_IDENTITY_WITH_FLAGS
                ? withLastSeenFeatureFlags(
                      window.POSTHOG_USER_IDENTITY_WITH_FLAGS,
                      readLastSeenFeatureFlags(),
                      getAppContext()?.current_user?.distinct_id,
                  )
                : {},
            opt_in_site_apps: true,
            disable_surveys: window.IMPERSONATED_SESSION,
            disable_product_tours: true,
            opt_out_capturing_by_default: window.IMPERSONATED_SESSION,
            __preview_deferred_init_extensions: isInDeferredInitSample(
                posthog.get_session_id(),
            ),
            error_tracking: {
                __capturePostHogExceptions: true,
            },
            metrics: {
                network: true,
                serviceName: "posthog-app",
                ...options.metrics,
            },
            // A page in a frame counts its own pageviews, so its events say so and analysis can filter them.
            // `register` would persist the property in storage the main window shares, so it is stamped per event.
            before_send: [
                ...(isEmbeddedPageFrame() ? [stampEmbeddedPageFrame] : []),
                ...(Array.isArray(options.beforeSend)
                    ? options.beforeSend
                    : options.beforeSend
                      ? [options.beforeSend]
                      : []),
            ],
            loaded: (loadedInstance) => {
                if (loadedInstance.sessionRecording) {
                    loadedInstance.sessionRecording._forceAllowLocalhostNetworkCapture = true;
                }

                if (window.IMPERSONATED_SESSION) {
                    loadedInstance.sessionManager?.resetSessionId();
                    loadedInstance.opt_out_capturing();
                } else {
                    loadedInstance.opt_in_capturing();

                    if (
                        !!window.POSTHOG_APP_CONTEXT?.preflight?.is_debug ||
                        !!loadedInstance.getFeatureFlag(
                            FEATURE_FLAGS.TRACK_DETACHED_ELEMENTS,
                        )
                    ) {
                        startDetachedElementTracking(loadedInstance);
                    }

                    if (
                        loadedInstance.getFeatureFlag(
                            FEATURE_FLAGS.TRACK_MEMORY_USAGE,
                        )
                    ) {
                        const hasMemory = "memory" in window.performance;
                        if (!hasMemory) {
                            return;
                        }

                        const thirtyMinutesInMs = 60000 * 30;
                        let intervalId: number | null = null;

                        const captureMemory = (
                            visibilityTrigger:
                                | "is_visible"
                                | "went_invisible"
                                | "went_visible",
                        ): void => {
                            // this is deprecated and not available in all browsers,
                            // but the supposed standard at https://developer.mozilla.org/en-US/docs/Web/API/Performance/measureUserAgentSpecificMemory
                            // isn't available in Chrome even so 🤷
                            const memory = (window.performance as any).memory;
                            if (memory && memory.usedJSHeapSize) {
                                loadedInstance.capture("memory_usage", {
                                    totalJSHeapSize: memory.totalJSHeapSize,
                                    usedJSHeapSize: memory.usedJSHeapSize,
                                    visibility_trigger: visibilityTrigger,
                                    pageIsVisible:
                                        document.visibilityState === "visible",
                                    pageIsFocused: document.hasFocus(),
                                });
                            }
                        };

                        const startInterval = (): void => {
                            if (intervalId !== null) {
                                return;
                            }
                            intervalId = window.setInterval(
                                () => captureMemory("is_visible"),
                                thirtyMinutesInMs,
                            );
                        };

                        const stopInterval = (): void => {
                            if (intervalId !== null) {
                                clearInterval(intervalId);
                                intervalId = null;
                            }
                        };

                        const onVisibilityChange = (): void => {
                            if (document.hidden) {
                                captureMemory("went_invisible");
                                stopInterval();
                            } else {
                                captureMemory("went_visible");
                                startInterval();
                            }
                        };

                        document.addEventListener(
                            "visibilitychange",
                            onVisibilityChange,
                        );

                        if (!document.hidden) {
                            startInterval();
                        }

                        window.addEventListener("beforeunload", () => {
                            stopInterval();
                            document.removeEventListener(
                                "visibilitychange",
                                onVisibilityChange,
                            );
                        });
                    }
                }

                // This is a helpful flag to set to automatically reset the recording session on load for testing multiple recordings
                const shouldResetSessionOnLoad = loadedInstance.getFeatureFlag(
                    FEATURE_FLAGS.SESSION_RESET_ON_LOAD,
                );
                if (shouldResetSessionOnLoad) {
                    loadedInstance.sessionManager?.resetSessionId();
                }

                // Make sure we have access to the object in window for debugging
                window.posthog = loadedInstance;
            },
            scroll_root_selector: ["main", "html"],
            autocapture: {
                capture_copied_text: true,
            },
            session_recording: {
                blockSelector: ".ph-replay-block",
                streamNetworkBody: true,
                ...options.sessionRecording,
            },
            person_profiles: "always",
            // posthog-js patches fetch to add X-POSTHOG-* tracing headers to these hosts. In OAuth
            // mode the app's own /api calls go cross-origin to one of them, where the cloud CORS
            // allowlist rejects those headers — so disable the feature then.
            tracing_headers: isOAuthMode()
                ? []
                : ["eu.posthog.com", "us.posthog.com"],
            __preview_disable_xhr_credentials: true,
            capture_performance: {
                //disabling to investigate if this is associated with memory leak in the posthog app
                web_vitals_attribution: false,
            },
            identity_distinct_id: window.JS_POSTHOG_IDENTITY_DISTINCT_ID,
            identity_hash: window.JS_POSTHOG_IDENTITY_HASH,
        });

        posthog.onFeatureFlags((_flags, variants, context) => {
            if (!context?.errorsLoading) {
                writeLastSeenFeatureFlags({
                    distinctId: posthog.get_distinct_id(),
                    featureFlags: variants,
                });
            }

            if (
                inStorybook() ||
                inStorybookTestRunner() ||
                !context?.errorsLoading
            ) {
                return;
            }

            posthog.capture("onFeatureFlags error");

            // Track that we failed to load feature flags
            window.POSTHOG_GLOBAL_ERRORS ||= {};
            window.POSTHOG_GLOBAL_ERRORS["onFeatureFlagsLoadError"] = true;
        });
    } else {
        posthog.init("fake_token", {
            autocapture: false,
            // Pages without a project key only need `posthog` calls to be safe no-ops. Without this,
            // init() fetches remote config and flags for the placeholder token from PostHog Cloud
            // before `loaded` can opt out.
            advanced_disable_flags: true,
            // `loaded` runs at the end of init(). An event captured before then stays in the request
            // queue, and the queue sends it to PostHog Cloud on page unload even after the opt-out.
            opt_out_capturing_by_default: true,
            loaded: function (ph) {
                ph.opt_out_capturing();
            },
        });
    }
}
