---
name: onboarding-videos
description: Add, replace, and optimize the looping demo videos in the onboarding "welcome" bento grid (packages/ui/src/features/onboarding). Covers the ffmpeg compression workflow (the scripts/optimize-onboarding-videos.mjs wrapper), the faststart + right-size best practices that keep playback smooth, the first-frame poster convention, and how to wire a new clip into WelcomeScreen. Use when onboarding demo clips feel laggy, when a clip is being added/swapped/re-recorded, or when posters and videos drift out of sync.
allowed-tools: Bash(node scripts/optimize-onboarding-videos.mjs:*), Bash(pnpm optimize:onboarding-videos:*), Bash(ffmpeg:*), Bash(ffprobe:*), Bash(npx biome check:*), Bash(pnpm --filter @posthog/ui typecheck:*)
---

# Onboarding bento demo videos

The first onboarding step (`WelcomeScreen`) shows a bento grid of feature cards.
A card with a `media` entry plays a short, muted, looping screen recording; cards
without one show a static placeholder. The featured (large, top-left) card is the
only one that plays at a time — hover just moves the highlight.

| Thing | Where |
| --- | --- |
| Clips + posters | `packages/ui/src/features/onboarding/assets/<feature>-<light\|dark>.{mp4,jpg}` |
| Wiring (`MEDIA` map, `startTime`) | `packages/ui/src/features/onboarding/components/WelcomeScreen.tsx` |
| `<video>` element + play/seek logic | `packages/ui/src/features/onboarding/components/FeatureBentoCard.tsx` |
| Optimizer script | `scripts/optimize-onboarding-videos.mjs` (`pnpm optimize:onboarding-videos`) |

## Why clips need optimizing (the "it feels laggy" fix)

Raw screen recordings hitch in this UI for two reasons, both fixed by re-encoding:

1. **`moov` atom at the end of the file.** Without faststart the player must read
   to EOF before it can start, so first-play and every seek stutter. We seek on
   mount and on every loop (`FeatureBentoCard` parks the clip on `videoStartTime`),
   so this bites constantly. Fix: `-movflags +faststart`.
2. **Resolution far larger than it renders.** The featured slot is never wider than
   ~500 CSS px (the grid is `max-w-[760px]`). Even at 2× retina that's ~1000px, but
   recordings come in at ~1876px. Decoding huge frames and downscaling them — on
   every play and during the framer-motion slot reflow — is wasted work. Fix: cap
   width at **1000px** (which also matches the poster width exactly).

Bitrate/size are usually already modest; **decode cost and startup are the lag**,
not bytes. Don't chase file size at the expense of width/faststart.

## Canonical encode target

H.264 · `yuv420p` · **≤1000px wide** (keep aspect, even height) · CRF 23 ·
`+faststart` · no audio. These live as constants at the top of
`scripts/optimize-onboarding-videos.mjs` — change them there, not ad-hoc.

## Optimize existing clips

```bash
pnpm optimize:onboarding-videos          # encode any clip not already optimized
pnpm optimize:onboarding-videos --dry-run   # show what would change
pnpm optimize:onboarding-videos --force     # re-encode all (after changing the target constants)
```

Requires ffmpeg (`brew install ffmpeg`). The script tags each output with a
`comment` marker, so re-runs skip already-optimized files — it's safe to run any
time, including right after dropping in a new clip. It rewrites files in place;
review the `git diff --stat` and the printed before/after sizes.

## Add or replace a clip

1. **Record** light + dark variants at **≥1000px wide**. The optimizer downscales to
   1000px but never upscales, so anything narrower ships soft — resolution is the one
   thing it can't fix for you. Keep it short (~10–13s); it loops.
2. **Name + drop** the files as `assets/<feature>-light.mp4` and
   `assets/<feature>-dark.mp4`. Two things bite every time:
   - Recordings almost always arrive with the **light variant unsuffixed**
     (`foo.mp4`, only `foo-dark.mp4` is tagged). Rename it to `foo-light.mp4`.
   - The source filename (e.g. whatever's in `~/Downloads`) is irrelevant — the
     `<feature>` prefix must be the **media id** you'll use in `WelcomeScreen` and
     follow the existing convention, not whatever the file was called.

   No `assets.d.ts` change needed — `*.mp4`/`*.jpg` are wildcard modules.
3. **Optimize**: `pnpm optimize:onboarding-videos`.
4. **Make the poster** — the still shown before play. **Use the clip's first frame**
   and leave `startTime` at 0, so the poster, the first played frame, and the loop
   point are all the same with nothing to keep in sync:

   ```bash
   ffmpeg -y -i assets/<feature>-<theme>.mp4 \
     -frames:v 1 -vf "scale=1000:-2:flags=lanczos" -q:v 3 \
     assets/<feature>-<theme>.jpg
   ```

5. **Wire it up** in `WelcomeScreen.tsx`. For a *new* media id, four edits, all keyed
   by the same slug: import the `.mp4` + `.jpg`, add the id to the `MediaId` union,
   add its entry to the `MEDIA` map (`startTime: 0`), and set `media: "<id>"` on the
   target `FeatureDef`.

### Replacing an existing clip

Keep the **same asset filename** and the wiring is untouched — none of step 5
applies. Drop the new file over `assets/<feature>-<theme>.mp4`, run the optimizer (a
fresh drop carries no skip-marker, so it re-encodes without `--force`), and
**regenerate that poster** (step 4). If you replace only one theme, re-check that
light and dark still share an aspect ratio — a clip with stray padding frames
differently from its sibling, and the gap shows when the user toggles theme.

## Poster = first frame (and startTime = 0)

`FeatureBentoCard` shows the poster while a card rests, then seeks the `<video>` to
`MEDIA[id].startTime` on mount and loops back there (not necessarily to 0). The
simple, default contract: **the poster is the clip's first frame and `startTime` is
0**, so the still, the first played frame, and the loop point are all identical —
nothing to keep in sync. Keep the poster the same pixel width as the clip (1000px)
so the poster→video swap is seamless.

`startTime` can start/loop mid-clip if you ever need it (the `code-review` clip uses
3s) — but then the poster MUST be that exact frame (`ffmpeg -ss <startTime> -i …`),
or the still jumps the instant playback starts. Prefer the first-frame default
unless you have a specific reason.

## Verify

```bash
# clips: moov should print BEFORE mdat, width ≤ 1000:
ffprobe -v trace <clip>.mp4 2>&1 | grep -o -m2 -E "type:'(moov|mdat)'"
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 <clip>.mp4

# wiring: a grown MediaId union may need a formatter reflow, so let biome fix it:
npx biome check --write packages/ui/src/features/onboarding/components/WelcomeScreen.tsx
pnpm --filter @posthog/ui typecheck
```

To confirm playback feels smooth in the real app, use the `test-electron-app`
skill to drive the running onboarding flow.
