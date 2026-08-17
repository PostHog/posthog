/**
 * Prototype-only canned answers. The real implementation will stream from the
 * PostHog AI conversations API over the shared `persist:main` session.
 */

export interface MockHeadline {
  value: string;
  label: string;
  delta: string;
  direction: "up" | "down";
}

export interface MockChart {
  kind: "line" | "bar";
  title: string;
  source: string;
  points: number[];
  labels: string[];
}

export interface MockBreakdownItem {
  label: string;
  value: string;
}

export interface MockResponse {
  matcher: RegExp;
  thinkingLabel: string;
  /** Paragraphs; `**bold**` runs are emphasized, `##...##` runs render amber. */
  paragraphs: string[];
  headline: MockHeadline;
  chart: MockChart;
  breakdown: MockBreakdownItem[];
  followUps: string[];
  copyText: string;
}

export const MOCK_RESPONSES: MockResponse[] = [
  {
    matcher: /signup/i,
    thinkingLabel: "Querying signups…",
    paragraphs: [
      "Best day in 3 weeks. Most of the lift came from **organic search** (+214) after the pricing page change shipped Monday.",
    ],
    headline: {
      value: "1,284",
      label: "Signups yesterday",
      delta: "12% vs prev. Tuesday",
      direction: "up",
    },
    chart: {
      kind: "line",
      title: "Signups · last 14 days",
      source: "via Trends",
      points: [
        620, 700, 640, 820, 760, 900, 840, 880, 930, 870, 1010, 980, 1140, 1284,
      ],
      labels: [
        "Jul 31",
        "",
        "",
        "",
        "Aug 4",
        "",
        "",
        "",
        "Aug 8",
        "",
        "",
        "",
        "Aug 12",
        "",
      ],
    },
    breakdown: [
      { label: "Organic search", value: "486" },
      { label: "Direct", value: "312" },
      { label: "Referral", value: "233" },
      { label: "Paid", value: "155" },
    ],
    followUps: ["Break down by country", "How many activated?"],
    copyText:
      "You got 1,284 signups yesterday, up 12% vs the previous Tuesday. Most of the lift came from organic search (+214) after the pricing page change shipped Monday. Top channels: organic search 486, direct 312, referral 233, paid 155.",
  },
  {
    matcher: /flag|onboarding|conversion/i,
    thinkingLabel: "Comparing conversion by flag variant…",
    paragraphs: [
      "Doesn't look like it. **new-onboarding-flow** is beating control and the lift is trending significant. One caveat: **mobile** users on the new flow convert **3.1pt worse**, worth a look at step 2 on small screens.",
    ],
    headline: {
      value: "34.2%",
      label: "Signup → activation, new flow",
      delta: "2.4pt vs control",
      direction: "up",
    },
    chart: {
      kind: "line",
      title: "Conversion by variant · last 14 days",
      source: "via Funnels",
      points: [
        30, 31, 30.5, 32, 31.5, 33, 32.5, 33.5, 33, 34, 33.8, 34.5, 34.1, 34.2,
      ],
      labels: [
        "Jul 31",
        "",
        "",
        "",
        "Aug 4",
        "",
        "",
        "",
        "Aug 8",
        "",
        "",
        "",
        "Aug 12",
        "",
      ],
    },
    breakdown: [
      { label: "New flow · desktop", value: "36.8%" },
      { label: "New flow · mobile", value: "28.4%" },
      { label: "Control · desktop", value: "33.1%" },
      { label: "Control · mobile", value: "31.5%" },
    ],
    followUps: ["Show step 2 drop-off on mobile", "Ship the winning variant?"],
    copyText:
      "Signup to activation conversion is 34.2% for new-onboarding-flow vs 31.8% for control (+2.4pt, trending significant). Caveat: mobile users on the new flow convert 3.1pt worse.",
  },
  {
    matcher: /.*/,
    thinkingLabel: "Looking at your data…",
    paragraphs: [
      "Up **6%** week over week, driven mostly by returning users in the EU. Want me to break that down by platform or cohort?",
    ],
    headline: {
      value: "48,310",
      label: "Weekly active users",
      delta: "6% week over week",
      direction: "up",
    },
    chart: {
      kind: "bar",
      title: "WAU · last 8 weeks",
      source: "via Trends",
      points: [39000, 40100, 41500, 42000, 43800, 44900, 45500, 48310],
      labels: ["W25", "W26", "W27", "W28", "W29", "W30", "W31", "W32"],
    },
    breakdown: [
      { label: "EU", value: "21,480" },
      { label: "US", value: "18,020" },
      { label: "APAC", value: "8,810" },
    ],
    followUps: ["Split by platform", "Which cohorts grew?"],
    copyText:
      "Weekly active users are at 48,310 this week, up 6% week over week, driven mostly by returning users in the EU. EU 21,480, US 18,020, APAC 8,810.",
  },
];

export function pickMockResponse(question: string): MockResponse {
  return (
    MOCK_RESPONSES.find((response) => response.matcher.test(question)) ??
    MOCK_RESPONSES[MOCK_RESPONSES.length - 1]
  );
}
