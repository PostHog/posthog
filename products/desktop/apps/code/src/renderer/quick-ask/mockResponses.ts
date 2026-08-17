/**
 * Prototype-only canned answers. The real implementation will stream from the
 * PostHog AI conversations API over the shared `persist:main` session.
 */

export interface MockResponse {
  matcher: RegExp;
  thinkingLabel: string;
  /** Paragraphs; `**bold**` runs are emphasized, `##...##` runs render amber. */
  paragraphs: string[];
  sparkline?: { label: string; source: string; points: number[] };
  copyText: string;
}

export const MOCK_RESPONSES: MockResponse[] = [
  {
    matcher: /signup/i,
    thinkingLabel: "Querying signups…",
    paragraphs: [
      "You got ##1,284 signups## yesterday, up **12%** vs the previous Tuesday and the best day in the last 3 weeks.",
      "Most of the lift came from **organic search** (+214) after the pricing page change shipped Monday.",
    ],
    sparkline: {
      label: "Signups · last 14 days",
      source: "via Trends",
      points: [
        620, 700, 640, 820, 760, 900, 840, 880, 930, 870, 1010, 980, 1140, 1284,
      ],
    },
    copyText:
      "You got 1,284 signups yesterday, up 12% vs the previous Tuesday. Most of the lift came from organic search (+214) after the pricing page change shipped Monday.",
  },
  {
    matcher: /flag|onboarding|conversion/i,
    thinkingLabel: "Comparing conversion by flag variant…",
    paragraphs: [
      "Doesn't look like it. Signup to activation conversion is ##34.2%## for users with **new-onboarding-flow** vs ##31.8%## for control, a **2.4pt** lift that is trending significant.",
      "One caveat: **mobile** users on the new flow convert **3.1pt worse**. Worth a look at step 2 on small screens.",
    ],
    sparkline: {
      label: "Conversion by variant · last 14 days",
      source: "via Funnels",
      points: [
        30, 31, 30.5, 32, 31.5, 33, 32.5, 33.5, 33, 34, 33.8, 34.5, 34.1, 34.2,
      ],
    },
    copyText:
      "Signup to activation conversion is 34.2% for new-onboarding-flow vs 31.8% for control (+2.4pt, trending significant). Caveat: mobile users on the new flow convert 3.1pt worse.",
  },
  {
    matcher: /.*/,
    thinkingLabel: "Looking at your data…",
    paragraphs: [
      "Weekly active users are at ##48,310## this week, up **6%** week over week, driven mostly by returning users in the EU.",
      "Want me to break that down by platform or cohort?",
    ],
    sparkline: {
      label: "WAU · last 8 weeks",
      source: "via Trends",
      points: [39000, 40100, 41500, 42000, 43800, 44900, 45500, 48310],
    },
    copyText:
      "Weekly active users are at 48,310 this week, up 6% week over week, driven mostly by returning users in the EU.",
  },
];

export function pickMockResponse(question: string): MockResponse {
  return (
    MOCK_RESPONSES.find((response) => response.matcher.test(question)) ??
    MOCK_RESPONSES[MOCK_RESPONSES.length - 1]
  );
}
