---
name: recording-demo-videos
description: >
  Records a captioned, PostHog-branded walkthrough video (MP4) of a feature running on the local
  PostHog stack, for a Loom, a Slack demo, or a PR. Use when asked to record a video, demo,
  walkthrough, or Loom of a change end to end, including flows that leave the app, such as an API
  call shown as a terminal card or an email arriving in the local inbox. The recorder drives the
  real app, zooms in on the beats the storyboard marks, adds RoundHog
  captions, a pointer, hedgehog stickers, and an optional ElevenLabs voiceover and music bed, and
  frames the video with title and end cards that carry the logo and a hedgehog from @posthog/brand.
  For a short animated WebP of one interaction in a PR description, use the reel mode of qa-frontend.
---

# Recording demo videos

A demo video shows a feature working, from the first click to the proof that it worked.
The recorder drives the real app on the local stack, so what the viewer sees is what the code does.
It writes a short MP4, usually under a minute, a contact sheet of frames to review, and a log.

The output looks like this: a title card with the logo and a hedgehog, the app with a caption bar and a pointer that glides to each click, terminal cards for API calls, and an end card.
Page loads stay out of the video, so it moves at reading speed.
A step can also zoom in on the button it clicks or on the detail it proves.
A voiceover can read the captions, a music bed can sit under it, and a step can pop in a hedgehog sticker with a short sound.

Use [qa-frontend](../qa-frontend/SKILL.md) instead for a reel: a short animated WebP of one interaction, made from stills, for a PR description.
For a raw take with no captions or narration, frame-perfect at 60 fps, PostHog staff can use `recording-web-demos` from the team skills store (`skill-get` in the PostHog MCP). It steps the page clock frame by frame, so it never judders.

## Workflow

### 1. Settle the brief

Settle three things with the developer before you record, render or write a storyboard:

- **Promo or demo.** A demo shows the real app working, from the first click to the proof. A promo sells the feature: it leads with the payoff, moves fast to music, and can leave the app behind. "A video for the launch" can mean either, so ask. This recorder makes demos. For a promo, [hogreel](references/branding.md#promo-videos) renders the video, and this recorder can supply clips of the app for it. Agree with the developer which tool makes the video before you continue.
- **A style reference**: a file or a URL of a video the developer wants this one to feel like. Match its pace, tone and framing.
- **Music**: yes or no, and the mood when yes.

The **final take** is the take with the voiceover and music that the developer gets. Every take before it is silent: no `voiceover` and no `music` in the storyboard.

### 2. Get the stack ready

The stack must be up and serving the code you want to show.
Start it with `hogli start -y -d` and `hogli wait`, or follow `/run-posthog`.
Check the processes the flow needs beyond the web app.
For example, workflow runs and email sends need the CDP workflow workers, which the default dev stack does not start.
[references/troubleshooting.md](references/troubleshooting.md) lists the ones that caught us.

The recorder needs `ffmpeg` and the repo's Python environment, which has Playwright.
On Linux without `apt`, fetch the static ffmpeg build the recorder's error names. It matches the machine's architecture.
It reads the brand assets from `frontend/node_modules/@posthog/brand`, so run `pnpm install` first if that directory is missing.

### 3. Seed the data the demo needs

Record in a local demo workspace, never in a workspace with real data, because the video can end up in a public PR.
`python manage.py setup_dev --no-data` creates one with the `test@posthog.com` user.
Seed everything else the flow needs with a short script: feature flags, objects to start from, API keys.

Invent all the data.
Use reserved domains (`example.com`) or a domain you control for addresses, and invented names.
Some flows validate a domain, for example the email sender refuses a domain without mail servers, so check what the flow accepts.

Each take changes state: it creates objects, sends emails, and bumps versions.
Write four small scripts for the demo:

- seed: creates the starting state.
- reset: puts the starting state back before every take.
- check: runs the flow once before the first take.
- preflight: asserts in seconds that the seeded data is still there. Set it as the storyboard's `preflight`, so a take with missing data stops before it records.

[references/seeding.md](references/seeding.md) shows how to work out what the flow needs and how to write each script.

### 4. Write the storyboard

A storyboard is a JSON file: optional title and end cards, then a list of steps.
Each step can navigate, click, type, wait, show a caption, or show an HTTP request as a terminal card and send it.
Read [references/storyboard.md](references/storyboard.md) for the format and a full example.

Plan the beats before you write steps:

1. The title card says what the feature does for the viewer, in one line.
2. Start in the state just before the new behavior. Skip the navigation a viewer already knows.
3. One step per action, with a caption that says what is happening and why it matters.
4. Show proof of the effect: the email in the inbox, the row in the table, the number in the chart.
5. The end card sums up the change in one line.

Captions are user-facing copy, so `/writing-user-facing-copy` applies: sentence case, one idea each, no em dashes.
Write them to be read aloud too, when the video has a voiceover.

#### Pacing

A demo that drags loses the viewer. Keep it short, and keep it moving.

- Aim for 30 to 60 seconds. Go past 90 seconds only when the flow needs every beat. Cut beats before you add time.
- Change something on screen at least every two seconds. A still frame is a pause, even with a caption on it.
- Show each idea once. Cut a step that proves nothing new.
- Keep captions under ten words. A long caption holds its step longer, and a long voiceover line holds it longer still.
- Leave `hold` unset. The defaults hold a caption for about a quarter of a second per word, at least one and a half seconds. With a voiceover, a step waits for its line to finish.
- Set `hold` only to give a sticker time to land or to make a navigation step shorter. Keep it at two seconds or less.
- Zoom on the two to five beats that matter: the key click, and the detail that proves it worked. A zoom on every step makes the video seasick.

For a voiceover or music, add `voiceover` or `music` to the storyboard.
They need an ElevenLabs API key in `ELEVENLABS_API_KEY`. Do not ask the developer to paste the key into the chat.
Without the key, the recorder leaves out the voiceover and generated music and records a captioned video.
The log lists what it left out under `skipped_without_elevenlabs_key`. Tell the developer, and point them to [references/troubleshooting.md](references/troubleshooting.md#elevenlabs-calls-fail) to set the key.
Settle the captions in a silent take first, because every changed line costs credits.

### 5. Get the cut approved

Before the final take, send the developer a voice-only cut and three stills, and wait for a yes:

- **Voice-only cut**: `--voice-only` writes the narration to `<output>.voice.mp3` without recording. Skip it when the video has no voiceover.
- **Three stills**: the title card and two key beats, with their captions. Take them from a silent take of the whole storyboard, with `ffmpeg -ss <seconds> -i <output>.mp4 -frames:v 1 still.png`.

Change the brief or the storyboard until the developer approves both.

When the video could go more than one way, such as two voices, two music moods or two pacings, make a **style board** for each option instead of a final take for each.
A style board is a cut-down storyboard of the first steps, about ten seconds long, with two voice lines:

- two stills from its silent take
- its silent take, as the motion
- its two voice lines, from `--voice-only`

The developer picks one board, and only that option gets a final take.
Generated music depends on the video's length in ten second steps, so the final take gets a new track in the same mood. Say so when you show the boards.

### 6. Record

From the root of the checkout:

```bash
uv run python .agents/skills/recording-demo-videos/scripts/record_demo.py path/to/storyboard.json
```

The script logs in, loads every page once to warm the dev server, then records.
It writes `<output>.mp4`, `<output>.sheet.png` and `<output>.log.json` next to the storyboard.
When a step fails, it writes `<output>.error.png` and exits non-zero. The log names the step.
To fix a late step, rehearse from it with `--from-step N`, where N is the step the log names.
The take starts at step N, on the page of the last `goto` before it, and writes `<output>.from-N.mp4`.
The steps before N do not run, so the data must already be in the state step N expects, such as right after the failed take.
When the step works, reset and record the whole take.

### 7. Review, then record again

Read the contact sheet before you share anything.
Most first takes need another one. Look for:

- pauses: frames where nothing changes for more than two seconds, or a `duration` in the log over 60 seconds. Remove the `hold`, shorten the caption, or cut the step.
- spinners, skeletons or empty tables where the step expected data. Add a `wait_for` on the content.
- numbers that disagree with what happened in the video.
- debug chrome, banners and toasts that distract. Add them to `hide_text` or `hide_selectors`.
- with a voiceover: the `voice` list in the log, which gives each line's start and length in the video. A line that runs long holds its step, so a step that lingers often has a long line. Trim the line.
- secrets, real names, or anything else that must not be public, in the pixels and in the captions.

Reset the data, then record again. Read individual frames with ffmpeg when the sheet is too small to judge.

### 8. Share

In a PostHog Desktop or cloud task, upload the MP4 as a task artifact.
For a PR, upload it with `hogli pr:upload-video` and paste the markdown it prints.
PR assets are public forever, so check the frames for private data before every upload.

## References

- [references/seeding.md](references/seeding.md): working out what a flow needs, and the seed, reset and check scripts.
- [references/storyboard.md](references/storyboard.md): the storyboard format, targets, variables and secrets, preflight, voiceover, music, and a full example.
- [references/branding.md](references/branding.md): where the brand assets come from, the rules for the logo, colors, type and hedgehogs, and hogreel.
- [references/troubleshooting.md](references/troubleshooting.md): failures we hit while recording, and their fixes.
