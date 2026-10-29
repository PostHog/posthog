# Branding

The recorder styles everything it adds with PostHog's brand: the title, end and terminal cards, the caption bar and the cursor.
The app itself is recorded as it is.

## Where the assets come from

Everything comes from `@posthog/brand`, the package behind [brand.posthog.com](https://brand.posthog.com), which the frontend already depends on.
The recorder reads it from `frontend/node_modules/@posthog/brand`, so nothing is downloaded and no brand file is copied into a skill or a PR.

- **Colors**: the brand palette, from the package's color tokens.
- **Type**: RoundHog, the brand typeface, embedded into the cards and the caption bar.
- **Logo**: rendered from the package's `Logo` component, full color on light cards and white on dark ones.
- **Hedgehogs**: the official illustrations, by slug.

The brand assets are PostHog trademarks under the PolyForm Strict License.
Use them in PostHog's own videos only.

## Rules

These come from brand.posthog.com and the brand handbook. The recorder follows them. Keep to them when you write a storyboard.

- **Logo**: the full-color logo goes on light backgrounds only, and the white logo on dark ones. Do not recolor, stretch or animate it, and never set "PostHog" in text next to the logomark.
- **Colors**: tangerine (`#FF5C1C`) is the accent, on the card bar, the caption edge and the click ring. A scene leans on two or three colors. Stage backgrounds are solid: cream (`#F4F3EE`) or dark (`#1D1F27`).
- **Type**: RoundHog in its brand weights: 500 Medium, 700 SemiBold, 800 Bold. There is no 600. Headings are sentence case.
- **Hedgehogs**: official art only. Never use AI-generated hedgehogs, and never edit one. Pick a hog that makes the card's point, not one that only fills space.

## Picking a hedgehog

List the slugs:

```bash
ls frontend/node_modules/@posthog/brand/dist/generated/hoggies/png | sed 's/\.png$//'
```

Or search them with their tags at [brand.posthog.com/hoggies](https://brand.posthog.com/hoggies).
Some that suit common demos: `mailbox` (email, messaging), `chart` (analytics), `explorer` (discovery, search), `robot` (AI, automation), `rocket` (launch), `party` (an end card).
An unknown slug fails the run and prints the full list.

## Promo videos

For a narrated or musical promo video, such as a launch reel, look at [PostHog/hogreel](https://github.com/PostHog/hogreel).
Team DevEx built it to render on-brand hype videos from HTML scenes, with a voiceover or a song.
It is private to the PostHog organization.
A demo video from this skill shows the real app working. A hogreel video sells it.
