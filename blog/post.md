# How we built user behavior analysis with multi-modal LLMs in 7 not-so-easy steps

We have tons of user behavior data - what pages they visit, what buttons they click, and so. And by a lot I mean billions of events and terabytes of stored Replay snapshots. The problem is obvious - there are too many user sessions to watch manually. So, we created a tool to watch them for you and highlight the issues. It's called Session summaries, we release it in beta today, and you can use it right now for free with PostHog AI.

Here I'll list step-by-step what we learned, where we messed up, and lots of practical tips on how to make user behavior analysis to work in production.

## Step 1: "Analyzing a single user session should be easy"

Let's forget about scaling for a moment, and focus just on a single user session - user visited a website or app, navigated a bit, did something useful, and left. The logic seems straightforward - take all the session events, send to LLM, get the summary.

{{ screenshot of the player with the summary }}
> (under the image text) *Here's how you can get a summary of a single session from chat, or Replay player*

However...

{{ TODO: Put a schema somewhere here? What to show though? Multiple types of events as input? }}

### Not all the context is equally useful

Usually, each user-generated event has lots of metadata attached to it. User info, URLs, type of event, CSS selectors, timestamps, and so. In PostHog case, a single session with all the metadata could easily hit a million of tokens. Even if we forget about pricing and context limits, providing too much data will force lost-in-the-middle effect - LLM will provide highlights on what happened at the very start or end, but completely miss the main part.

**Our approach:**

- Start with the "what I need 100%" approach, keeping minimal set of events and fields, adding new ones only if they increase the quality of the summary.
- Mappings for everything. If you event data include URLs - use `url_N` alias and attach mapping. Same for tab ids, and any repeating parameters.
- Use CSV input. Neither JSON no TOON (heh) will get you the same generation quality per input token.

### Parallelization breaks the narrative

If the user spent multiple hours on the website, their session could be huge. If you have lots of such users (like we do), it makes sense to start with splitting such sessions in segments and then analyze each one in parallel improve latency. It's a trap. If LLM doesn't know what happened before or after, it loses a critical context on what the current segment events actually means, so the combined result is worthless.

**Our approach:**

- As stupid as it sounds, just do segmenting and analysis in one very large call, so LLM knows everything.
- If you decide to go with segmenting - go sequential, so when analyzing segment #2, it has context on what happened in segment #1. You will still lose on "what happened next" part and it will be crazy slow though.
- Hope that your users are ok with waiting for a couple of minutes. Using faster models (like OpenAI `nano` ones) can allow you to stream the summary after 10-15s, but thinking models on "high" provide better results quality-wise, and quality is the goal.

### Crying wolf effect

Fast-growing products (startups specifically) have a bad habit of generating lots of exceptions, especially frontend ones. LLMs seems them, panics, and generates a summary of the session where the user completely failed in all their goals. In reality the user successfully got what they came for, and didn't even notice these exceptions.

**Our approach:**

- Programmatically pre-filter events that look like exceptions, especially if one causes multiple others as avalanche and they create a context that LLM can't ignore. For example, drop all JS exceptions that aren't API errors.
- It won't save you anyway (Check Step 2).

## Step 2: See what the user sees

Even if you find a great way to reduce noise, thec ore problem remained - we can't be sure if the issues that LLM highlighted actually impacted users. We can see TypeError in logs, but the retry happened in 200ms, so it didn't affect the user journey one beat. But what if we generate a video of the session? Then we can see what the user saw.

{{ scheme/graph of the video validation logic }}
> (under the image text) *For each blocking issue, we generate a short video clip and ask the multi-modal LLM to verify what actually happened*

When the single-session summary flags something as a "blocking error" - an exception that supposedly prevented the user from completing their goal - we don't trust it blindly. Instead, we:

1. Generate a ~10-second video clip, starting a couple seconds before the flagged event
2. Send the clip to a multi-modal LLM to either comfirm or deny the issue
3. Transcribe what happened, and update the summary

## Why not to use video

At the first glance using just the video seems like a perfect solution. With Gemini multi-modal models pricing (especially if running batches) you can transcribe multiple ours of user sessions for less than a cent. You can go even lower, if you can use open-source models.

LLMs don't need 30fps

Video files are heavy. A full session recording could be hundreds of megabytes. Sending that to an LLM would be slow and expensive.

But here's the thing - LLMs process video by sampling frames, typically around 1 frame per second. They don't need smooth playback, they need enough visual snapshots to understand what's happening.

Our approach:

- Render validation videos at 8x playback speed. A 12-second real-time clip becomes ~1.5 seconds of video.
- This gives the LLM the same information density (one meaningful frame per real-time second) in a much smaller file.
- Skip the first 2 seconds of rendered video - early frames often have rendering artifacts from the replay engine warming up.
- Use Gemini 2.5 Flash for video understanding. We tested multiple models; it hit the best balance of speed, accuracy, and ability to notice UI details.

Not every issue deserves a video

Video validation adds latency and cost. Generating clips, uploading them, waiting for multi-modal LLM responses - it adds up. For a report covering 100 sessions, validating every minor issue would be
prohibitively slow.

Our approach:

- Only generate videos for blocking issues - errors that appear to completely stop user progress.
- Minor friction (slow loads, small UI glitches) gets flagged from events alone. The cost of a false positive is low.
- For blocking issues, the cost of a false positive is high (you might panic-fix something that isn't broken), so video validation is worth it.
- Accept that some videos will fail to generate (replay data issues, edge cases). If more than 50% fail, we surface that in the report rather than silently skipping validation.

The result

Video validation transformed our summaries from "here are all the scary things in the logs" to "here's what actually went wrong for the user." False positives dropped significantly. When the summary says
"blocking error," you can trust it.

But we're still talking about single sessions. The real value comes when you can spot patterns across dozens or hundreds of sessions. That requires a different architecture entirely.

Step 3: Token economics at scale

---

The crying wolf problem from Step 1 has no good solution with events alone. The only way to know if an error actually impacted the user is to look at what they saw on their screen. So we added video
validation - for critical moments, we generate a short clip and ask the LLM to verify.

{{ screenshot of video validation UI showing a flagged issue with video context }}
When we flag a blocking issue, we generate a video clip to confirm it actually happened from the user's perspective

How video validation works

When the single-session summary flags something as a "blocking error" - an exception that supposedly prevented the user from completing their goal - we don't trust it blindly. Instead:

1. Generate a 12-second video clip, starting 7 seconds before the flagged event
2. Send the clip to a multi-modal LLM (Gemini 2.5 Flash)
3. Ask: "Did this error actually block the user? What do you see on screen?"
4. Update the summary based on visual confirmation

The result: false positives get caught. An exception that fired but didn't break anything visible gets downgraded. A real blocker that crashed the UI gets confirmed.

LLMs don't need 60fps

Here's a fun discovery: LLMs analyze video at roughly 1 frame per second. They're not watching motion - they're reading a sequence of screenshots. This means:

- We render videos at 8x playback speed
- A 12-second clip becomes ~1.5 seconds of actual video
- File sizes drop dramatically, upload times shrink
- Same information density for the LLM, fraction of the cost

Our approach:

- Only validate high-severity issues. Video generation isn't free - we skip it for minor friction and focus on blocking errors.
- Keep clips short and focused. 12 seconds centered on the event gives enough context without overwhelming the model.
- Use specialized models for video. We use Gemini 2.5 Flash for video understanding - it's fast and catches visual details that matter.

What we validate (and what we don't)

Video validation is expensive, so we're selective:

We validate:

- Blocking exceptions (did the error actually break the UI?)
- Confusion moments (was the user actually stuck, or just reading?)
- Abandonments (did they rage-quit or calmly leave?)

We don't validate:

- Minor friction (rageclicks on slow buttons)
- Successful flows (no need to confirm things went well)
- Non-blocking errors (background failures the user never saw)

The tradeoff

Video validation adds latency and cost. For a single session, it might add 10-20 seconds. For 100 sessions with multiple flagged issues each, it adds up. We decided it's worth it - a trustworthy summary
beats a fast but noisy one.

But this only solves single-session analysis. The real value isn't knowing what went wrong in one session - it's finding patterns across hundreds of sessions. That's Step 3.

Step 3: ...
