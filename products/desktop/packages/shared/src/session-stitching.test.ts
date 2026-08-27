import { describe, expect, it } from "vitest";
import {
  appendSessionIdIfPostHogUrl,
  getStitchableOrigins,
  POSTHOG_SESSION_ID_URL_PARAM,
} from "./session-stitching";

const SESSION_ID = "01890a5d-ac96-774b-bcce-b302099a8057";
const PROD_ORIGINS = getStitchableOrigins(false);
const DEV_ORIGINS = getStitchableOrigins(true);

describe("appendSessionIdIfPostHogUrl", () => {
  it.each([
    ["https://us.posthog.com/replay/recent"],
    ["https://eu.posthog.com/project/2/insights"],
  ])("decorates %s", (url) => {
    expect(appendSessionIdIfPostHogUrl(url, SESSION_ID, PROD_ORIGINS)).toBe(
      `${url}?${POSTHOG_SESSION_ID_URL_PARAM}=${SESSION_ID}`,
    );
  });

  it("preserves existing query params and hash", () => {
    const result = appendSessionIdIfPostHogUrl(
      "https://us.posthog.com/insights?foo=1#panel=activity",
      SESSION_ID,
      PROD_ORIGINS,
    );
    expect(result).toBe(
      `https://us.posthog.com/insights?foo=1&${POSTHOG_SESSION_ID_URL_PARAM}=${SESSION_ID}#panel=activity`,
    );
  });

  it("overwrites a pre-existing session id param instead of duplicating it", () => {
    const spoofed = `https://us.posthog.com/insights?${POSTHOG_SESSION_ID_URL_PARAM}=01890a5d-ac96-774b-bcce-b30209ffffff`;
    const result = appendSessionIdIfPostHogUrl(
      spoofed,
      SESSION_ID,
      PROD_ORIGINS,
    );
    expect(result).toBe(
      `https://us.posthog.com/insights?${POSTHOG_SESSION_ID_URL_PARAM}=${SESSION_ID}`,
    );
  });

  it.each([
    ["a non-PostHog host", "https://github.com/PostHog/posthog/pull/1"],
    ["a lookalike suffix domain", "https://us.posthog.com.evil.com/insights"],
    ["a lookalike prefix subdomain", "https://notus.posthog.com/insights"],
    ["a non-http scheme", "mailto:hey@posthog.com"],
    ["a file url", "file:///var/log/app.log"],
    ["an unparseable url", "not a url"],
    ["the dev origin outside dev builds", "http://localhost:8010/insights"],
  ])("leaves %s undecorated", (_name, url) => {
    expect(appendSessionIdIfPostHogUrl(url, SESSION_ID, PROD_ORIGINS)).toBe(
      url,
    );
  });

  it.each([
    ["a UUIDv4", "9b0813c0-b661-4f47-92ca-1e0890a3a8c4"],
    ["garbage", "not-a-session-id"],
    [
      "a UUIDv7 shape with non-hex characters",
      "zzzzzzzz-zzzz-7zzz-8zzz-zzzzzzzzzzzz",
    ],
  ])("refuses to decorate with %s as the session id", (_name, sessionId) => {
    const url = "https://us.posthog.com/insights";
    expect(appendSessionIdIfPostHogUrl(url, sessionId, PROD_ORIGINS)).toBe(url);
  });

  it("decorates the dev origin only when dev is included", () => {
    const url = "http://localhost:8010/insights";
    expect(appendSessionIdIfPostHogUrl(url, SESSION_ID, DEV_ORIGINS)).toBe(
      `${url}?${POSTHOG_SESSION_ID_URL_PARAM}=${SESSION_ID}`,
    );
  });
});
