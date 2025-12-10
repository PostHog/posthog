<p align="center">
  <img alt="posthoglogo" src="https://user-images.githubusercontent.com/65415371/205059737-c8a4f836-4889-4654-902e-f302b187b6a0.png">
</p>
<p align="center">
  <a href='https://posthog.com/contributors'><img alt="GitHub contributors" src="https://img.shields.io/github/contributors/posthog/posthog"/></a>
  <a href='http://makeapullrequest.com'><img alt='PRs Welcome' src='https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=shields'/></a>
  <img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/posthog/posthog"/>
  <a href="https://github.com/PostHog/posthog/commits/master"><img alt="GitHub commit activity" src="https://img.shields.io/github/commit-activity/m/posthog/posthog"/> </a>
  <a href="https://github.com/PostHog/posthog/issues?q=is%3Aissue%20state%3Aclosed"><img alt="GitHub closed issues" src="https://img.shields.io/github/issues-closed/posthog/posthog"/> </a>
</p>

<p align="center">
  <a href="https://posthog.com/docs">Ship's Log</a> - <a href="https://posthog.com/community">Crew</a> - <a href="https://posthog.com/roadmap">Treasure Map</a> - <a href="https://posthog.com/why">Why sail with PostHog?</a> - <a href="https://posthog.com/changelog">Captain's Log</a> - <a href="https://github.com/PostHog/posthog/issues/new?assignees=&labels=bug&template=bug_report.yml">Report leaks in the hull</a>
</p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=2jQco8hEvTI">
    <img src="https://res.cloudinary.com/dmukukwp6/image/upload/demo_thumb_68d0d8d56d" alt="PostHog Demonstration">
  </a>
</p>

## PostHog be an all-in-one, open source vessel fer buildin' successful products, arr!

[PostHog](https://posthog.com/) provides every tool ye need to build a successful product, includin' these fine treasures:

- [Product analytics](https://posthog.com/product-analytics): Autocapture or manually chart yer event-based analytics to understand how scallywags behave and analyze data with fancy visualizations or SQL, savvy?
- [Web analytics](https://posthog.com/web-analytics): Monitor web traffic and user sessions with a dashboard fit fer a captain. Keep an eye on conversions, web vitals, and yer doubloons.
- [Session replays](https://posthog.com/session-replay): Spy on real user sessions of landlubbers interactin' with yer website or mobile app to diagnose issues and understand their behavior, har har!
- [Feature flags](https://posthog.com/feature-flags): Safely hoist new features to select crew members or groups with feature flags, without sinkin' the ship.
- [Experiments](https://posthog.com/experiments): Test changes and measure their impact on yer treasure metrics. Set up experiments with no code required, even a cabin boy could do it!
- [Error tracking](https://posthog.com/error-tracking): Track errors, get alerts when the ship be takin' on water, and patch the holes to improve yer vessel.
- [Surveys](https://posthog.com/surveys): Ask yer crew anything with our collection of no-code survey templates, or build custom questionnaires with our survey builder.
- [Data warehouse](https://posthog.com/data-warehouse): Sync data from external ports like Stripe, Hubspot, yer data warehouse, and more. Query it alongside yer product data, all in one hold.
- [Data pipelines](https://posthog.com/cdp): Run custom filters and transformations on yer incoming cargo. Send it to 25+ tools or any webhook in real time, or batch export large amounts to yer warehouse.
- [LLM analytics](https://posthog.com/docs/llm-analytics): Capture traces, generations, latency, and cost fer yer LLM-powered vessel.

Best of all, every bit of this bounty be free to use with a [generous monthly free tier](https://posthog.com/pricing) fer each product. Set sail by signin' up fer [PostHog Cloud US](https://us.posthog.com/signup) or [PostHog Cloud EU](https://eu.posthog.com/signup), matey!

## Navigator's Chart

- [PostHog be an all-in-one, open source vessel fer buildin' successful products](#posthog-be-an-all-in-one-open-source-vessel-fer-buildin-successful-products-arr)
- [Navigator's Chart](#navigators-chart)
- [Settin' sail with PostHog](#settin-sail-with-posthog)
  - [PostHog Cloud (Recommended fer landlubbers)](#posthog-cloud-recommended-fer-landlubbers)
  - [Hostin' yer own ship (Advanced - fer seasoned sailors)](#hostin-yer-own-ship-advanced---fer-seasoned-sailors)
- [Riggin' up PostHog](#riggin-up-posthog)
- [Learnin' more about PostHog](#learnin-more-about-posthog)
- [Joinin' the crew](#joinin-the-crew)
- [Open-source vs. paid](#open-source-vs-paid)
- [We be hirin'!](#we-be-hirin)

## Settin' sail with PostHog

### PostHog Cloud (Recommended fer landlubbers)

The fastest and most seaworthy way to get started with PostHog be signin' up fer free to [PostHog Cloud](https://us.posthog.com/signup) or [PostHog Cloud EU](https://eu.posthog.com/signup). Yer first 1 million events, 5k recordings, 1M flag requests, 100k exceptions, and 1500 survey responses be free every month, after which ye pay based on what ye plunder.

### Hostin' yer own ship (Advanced - fer seasoned sailors)

If ye want to captain yer own vessel and self-host PostHog, ye can deploy a hobby instance in one line on Linux with Docker (recommended 4GB memory fer smooth sailin'):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/deploy-hobby)"
```

Open source deployments should handle approximately 100k events per month, after which we recommend [migratin' to PostHog Cloud](https://posthog.com/docs/migrate/migrate-to-cloud) lest ye run aground.

We _do not_ provide customer support or offer guarantees fer open source deployments, arr. See our [self-hostin' scroll](https://posthog.com/docs/self-host), [troubleshootin' guide](https://posthog.com/docs/self-host/deploy/troubleshooting), and [disclaimer](https://posthog.com/docs/self-host/open-source/disclaimer) fer more info.

## Riggin' up PostHog

Once ye've got a PostHog instance aboard, ye can rig it up by installin' our [JavaScript web snippet](https://posthog.com/docs/getting-started/install?tab=snippet), one of [our SDKs](https://posthog.com/docs/getting-started/install?tab=sdks), or by [usin' our API](https://posthog.com/docs/getting-started/install?tab=api).

We have SDKs and libraries fer popular languages and frameworks, like these fine tools:

| Frontend                                              | Mobile                                                          | Backend                                             |
| ----------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------- |
| [JavaScript](https://posthog.com/docs/libraries/js)   | [React Native](https://posthog.com/docs/libraries/react-native) | [Python](https://posthog.com/docs/libraries/python) |
| [Next.js](https://posthog.com/docs/libraries/next-js) | [Android](https://posthog.com/docs/libraries/android)           | [Node](https://posthog.com/docs/libraries/node)     |
| [React](https://posthog.com/docs/libraries/react)     | [iOS](https://posthog.com/docs/libraries/ios)                   | [PHP](https://posthog.com/docs/libraries/php)       |
| [Vue](https://posthog.com/docs/libraries/vue-js)      | [Flutter](https://posthog.com/docs/libraries/flutter)           | [Ruby](https://posthog.com/docs/libraries/ruby)     |

Beyond this bounty, we have scrolls and guides fer [Go](https://posthog.com/docs/libraries/go), [.NET/C#](https://posthog.com/docs/libraries/dotnet), [Django](https://posthog.com/docs/libraries/django), [Angular](https://posthog.com/docs/libraries/angular), [WordPress](https://posthog.com/docs/libraries/wordpress), [Webflow](https://posthog.com/docs/libraries/webflow), and more treasures.

Once ye've hoisted PostHog aboard, consult our [product scrolls](https://posthog.com/docs/product-os) fer more wisdom on how to set up [product analytics](https://posthog.com/docs/product-analytics/capture-events), [web analytics](https://posthog.com/docs/web-analytics/getting-started), [session replays](https://posthog.com/docs/session-replay/how-to-watch-recordings), [feature flags](https://posthog.com/docs/feature-flags/creating-feature-flags), [experiments](https://posthog.com/docs/experiments/creating-an-experiment), [error tracking](https://posthog.com/docs/error-tracking/installation#setting-up-exception-autocapture), [surveys](https://posthog.com/docs/surveys/installation), [data warehouse](https://posthog.com/docs/cdp/sources), and more booty.

## Learnin' more about PostHog

Our code ain't the only thing that be open source 😳. We also open source our [company handbook](https://posthog.com/handbook) which details our [strategy](https://posthog.com/handbook/why-does-posthog-exist), [ways of workin'](https://posthog.com/handbook/company/culture), and [ship's protocols](https://posthog.com/handbook/team-structure).

Curious about how to plunder the most from PostHog? We scribed a guide to [winnin' with PostHog](https://posthog.com/docs/new-to-posthog/getting-hogpilled) which walks ye through the basics of [measurin' activation](https://posthog.com/docs/new-to-posthog/activation), [trackin' retention](https://posthog.com/docs/new-to-posthog/retention), and [capturin' revenue](https://posthog.com/docs/new-to-posthog/revenue).

## Joinin' the crew

We <3 contributions big and small from all ye scallywags:

- Vote on features or get early access to beta functionality in our [treasure map](https://posthog.com/roadmap)
- Open a PR (see our instructions on [developin' PostHog locally](https://posthog.com/handbook/engineering/developing-locally))
- Submit a [feature request](https://github.com/PostHog/posthog/issues/new?assignees=&labels=enhancement%2C+feature&template=feature_request.yml) or [bug report](https://github.com/PostHog/posthog/issues/new?assignees=&labels=bug&template=bug_report.yml) if ye spot somethin' amiss

## Open-source vs. paid

This here vessel be available under the [MIT expat license](https://github.com/PostHog/posthog/blob/master/LICENSE), except fer the `ee` directory (which has its [license here](https://github.com/PostHog/posthog/blob/master/ee/LICENSE)) if applicable.

Need _absolutely 💯% FOSS_, ye say? Check out our [posthog-foss](https://github.com/PostHog/posthog-foss) repository, which be purged of all proprietary code and features.

The pricin' fer our paid plan be completely transparent and available on [our pricin' page](https://posthog.com/pricing).

## We be hirin'!

<img src="https://res.cloudinary.com/dmukukwp6/image/upload/v1/posthog.com/src/components/Home/images/mission-control-hog" alt="Hedgehog working on a Mission Control Center" width="350px"/>

Ahoy! If ye be readin' this, ye've proven yerself as a dedicated README reader, savvy?

Ye might also make a fine addition to our crew. We be growin' fast [and would love fer ye to join us](https://posthog.com/careers) on this voyage!
