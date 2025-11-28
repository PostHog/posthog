# How we built user behavior analysis with multi-modal LLMs in 5 not-so-easy steps

We have tons of user behavior data - what pages they visit, what buttons they click, and so, stored as sessions. And by tons I mean billions of events and terabytes of stored Replay snapshots. The problem is obvious - there are too many user sessions to watch manually. So, we created a tool to watch them for you and highlight the issues. It's called Session summaries, we release it in beta today, and you can use it right now for free with PostHog AI.

Here I'll list step-by-step what we learned, where we messed up, and lots of practical tips on how to make user behavior analysis to work in production.

> The steps below assume that you use (or develop) a user behavior analytics service (like PostHog, Hotjar, Microsoft Clarity, and similar), so you have access to user-generated events, and recordings of what the user did on your website.

## Step 1: "Analyzing a single user session should be easy"

Let's forget about scaling for a moment, and focus just on a single user session - user visited a website or app, navigated a bit, did something useful, and left. The logic seems straightforward - take all the session events, send to LLM, get the summary.

{{ screenshot of the player with the summary }}

> (under the image text) _Here's how you can get a summary of a single session from chat, or Replay player_

However...

{{ TODO: Put a schema somewhere here? What to show though? Multiple types of events as input? }}

### Not all the context is equally useful

Usually, each user-generated event has lots of metadata attached to it. User info, URLs, type of event, CSS selectors, timestamps, and so. In PostHog case, a single session with all the metadata could easily hit a million of tokens. Even if we forget about pricing and context limits, providing too much data will force lost-in-the-middle effect - LLM will provide highlights on what happened at the very start or end, but completely miss the main part.

**Our approach:**

- We start with the "what I need 100%" approach, keeping minimal set of events and fields, adding new ones only if they increase the quality of the summary.
- Mappings for everything. If event data includes URLs - we use `url_N` alias and attach mapping. Same for tab ids, and any repeating parameters.
- CSV input. Neither JSON no TOON (heh) will provide the same generation quality per input token.
- We don't return JSON either. If it works with free text - awesome, if not - we return YAML or CSV.

### Parallelization breaks the narrative

If the user spent multiple hours on the website, their session could be huge. If you have lots of such users (like we do), it makes sense to start with splitting such sessions in segments and then analyze each one in parallel improve latency. It's a trap. If LLM doesn't know what happened before or after, it loses a critical context on what the current segment events actually means, so the combined result is worthless.

**Our approach:**

- As stupid as it sounds, we just do segmenting and analysis in one very large call, so LLM knows everything.
- If to decide to go with segmenting - go sequential, so when analyzing segment #2, it has context on what happened in segment #1. "what happened next" part will be lost anyway, and it will be crazy slow though.
- Hope that users are ok with waiting for a couple of minutes. Using faster models (like OpenAI `nano` ones) can allow streaming the summary after 10-15s, but thinking models on "high" provide better results quality-wise, and quality is the goal.

### Crying wolf effect

Fast-growing products (startups specifically) have a bad habit of generating lots of exceptions, especially frontend ones. LLMs seems them, panics, and generates a summary of the session where the user completely failed in all their goals. In reality the user successfully got what they came for, and didn't even notice these exceptions.

**Our approach:**

- We programmatically pre-filter events that look like exceptions, especially if one causes multiple others as avalanche and they create a context that LLM can't ignore. For example, drop all JS exceptions that aren't API errors.
- It won't save us anyway (Check Step 2).

## Step 2: See what the user sees

Even with noise reduction, the core problem remained - we couldn't be sure if the issues LLM highlighted actually impacted users. A TypeError in logs looks scary, but if a retry succeeded in 200ms, the user never noticed. But what if we generate a video of the session? What if we could see what the user saw?

{{ scheme/graph of the video validation logic }}

> (under the image text) _For each blocking issue, we generate a short video clip and ask the multi-modal LLM to verify what actually happened_

When the single-session summary flags something as a "blocking error" - an exception that supposedly prevented the user from completing their goal - we don't trust it blindly. Instead, we:

- Generate a ~10-second video clip, starting a couple seconds before the flagged event
- Send the clip to a multi-modal LLM to transcribe the video
- Confirm or deny the issue, and update the summary

And it works pretty well. But also leads to the question - why not use only video? Why use events at all?

### Video explains the issue, but not the reason

If we use only video - we can see that the user visited the page, waited for 5 seconds, and left. But we don't see Clickhouse timeout error. Or outdated Redis cache being hit. Or malformed query parameter in the user URL. So, we know what happened, but can't generate a proper issue, as it will require lots of manual investigation - then why read the summary in the first place?

**Our approach:**

- Option #1 (current): We combine videos with issues highlighted by LLM from the events, to triage them before surfacing
- Option #2 (in progress): Transcribe all the videos of user sessions and combine them with events, creating complete blobs of data that will (almost) never hallucinate when summarized

Option #2 is in progress (and not in production yet) mostly because...

### Videos are heavy

At the first glance, transcribing all the user session videos seems like a no-brainer. For example, Gemini Flash multi-modal models cost 10-20 times cheaper than thinking LLMs from Anthropic or OpenAI (or even Gemini's own). It can go even lower with open-source models.

However, let's try basic math, using numbers from now (end of 2025). One frame of video in a good-enough resolution costs 258 tokens of Gemini Flash. If `1 frame per second * 60 seconds in a minute * 60 minutes in a hour * 258 tokens = 929k tokens`. Meaning, analyzing just one large-ish session already costs a million tokens. We can use even ligher models and even worse resolution, but at some moment the quality drop is too much.

Also these models are this cheap because they aren't exactly clever. We can ask it to transcribe what's on the screen well enough, but it won't be able to make meaningful conclusions. So, either we need to use way more expensive model from the start, or we need another model to analyze transcription after that.

**Our approach:**

- Don't analyze the whole video - there are at least 40-50-60% of inactivity that we can skip, and pay to transcribe only parts where the user did something. Though, we need either events or snapshots to find these parts.
- Don't analyze all the videos - there's a clear set of parameters (like event count, active duration) that can be used to decide if it's worthwhile to check the session

### Videos are heavy (one more time)

Even with all the optimizations above, video files add up. A 10-second clip at 1080p can be 7-10MB. Multiply by hundreds of thousands of sessions and we're looking at terabytes of storage costs daily. The example is obviously laughable, but even with regular `.mp4` format (tens of times smaller) it easy to get to terabytes pretty fast.

**Our approach:**

- We use `.webm`. It's roughly half size of the `.mp4`, supported by most multi-modal models, and can be played by most browsers by default (in UI or not).
- We render videos at 8-10x - 1 frame per second is usually enough for LLM to understand the context well. However, `puppeteer` or `playwright` have different keyframe settings, so after some point speed up will mean the data loss.

## Step 3: Analyze lots of sessions at once

A single session summary is useful enough, true, but watching one session at a time doesn't solve the original problem - there are thousands of sessions, and we need to find issues across them. As it's a beta, we decided to start small, with 100-session chunks. It won't cover all the sessions, but it can cover a good enough sample (or a specific org), and already saves tons of time.

{{ screenshot of the group report UI showing patterns }}

> (under the image text) _You can check pattern based on severity and issue types_

The session group summary surfaces patterns across sessions, with severity, affected session count, and specific examples. The hard part is, obviously, how to extract these patterns.

### Patterns are hard to catch

In the ideal world, we would just send 100 single session summaries in one LLM call, and get back a summary for all the patterns. Sadly, it doesn't work on multiple levels. Firstly, we will just hit context limits of LLMs, as enriched summaries are pretty heavy with metadata. Secondly, even if they fit - we would hit exactly the same lost-in-the-middle problem, with start/end sessions getting way more attention.

Also, we could've just picked a sample of sessions and select patterns from them, but then the quality of the final report will be too dependent on our luck in picking the initial sessions. LLMs love finding patterns, but without proper control we would've gotten either duplicates or incredibly insightful "wow, users clicked buttons" ones.

**Our approach:**
We use a four-phase pipeline instead of a single prompt:

1. Summarize each session individually (in parallel)
2. Extract patterns from summaries in chunks of meaningful size (to keep attention in the middle)
3. Combine patterns extracted from each chunk, by either joining similar ones or extending the list
4. Iterate over chunks of single session summaries to assign events back to patterns for concrete examples

{{ diagram of the four-phase pipeline }}

> (under the image text) _Sessions → Parallel summaries → Chunked pattern extraction → Combine/dedupe → Event assignment → Final report_

### Crying wolf effect - Patterns edition

Even if we got patterns - there's just too much data to process easily, so we need to rank them properly. For example, a blocking error that happens once in 100 sessions is annoying. The same error in 80 sessions is critical. Or, the exception could happen 10 times, but just for a single user out of 100, and saying "issue X happened 15 times" could cause a false alarm.

**Our approach:**

- We limit 1 example per session per pattern. So, if the report says "happened 15 times" you can be sure it happened in 15 different sessions, not one user rage-clicking the same broken button.
- We calculate detailed pattern statistics: occurrence count, affected sessions, percentage of total, severity
- The default report shows only issues with blocking errors by default, but you can show other types if you want to dig deeper

### Patterns need to be verifiable

Extracting patterns is only half the job. If users can't verify the patterns are real, they won't trust the report. "Users experience checkout timeouts" is useful. "Users experience checkout timeouts - here are 5 specific sessions where it happened, with timestamps and video clips" is actionable.

To make it work, we needed a way to easily display the whole story to the user and give them the tools to validate the issue themselves. So we did.

{{ screenshot of a specific issue modal }}

> (under the image text) _TODO_

**Our approach:**

- We display not just the issue, but also the segment that issue was part of, what happened before the issue, and what happened after
- Timestamp and event type of the issue is clear, and easy to validate
- Even easier, as we load the video of the session at the moment it happened (actually, a couple of seconds before)

<!-- ## Step 4: Make it work reliably with (RAW STEP, EDITING)

Now we got a pipeline that works - single session summaries, video validation, pattern extraction across 100 sessions. The problem? It's fragile. We're making ~150 LLM calls per report, any of which can fail. Timeouts, rate limits, malformed responses, hallucinated output that fails validation. If the whole thing falls apart because of one bad response, the feature is unusable.

{{ diagram of the Temporal workflow architecture }}

> (under the image text) Temporal orchestrates the entire pipeline: parallel summaries, chunked extraction, pattern assignment - with failure handling at each stage

### LLM calls fail, and that's fine

When you're calling LLMs at scale, failures aren't edge cases - they're expected behavior. A model might timeout. A response might be malformed JSON (or YAML, in our case). The output might hallucinate event IDs that don't exist. Treating every failure as fatal means your feature never works in production.

**Our approach:**

- We set failure thresholds instead of failing on first error:
- Session summaries: if less than 50% succeed, abort. Otherwise, continue with what we have.
- Pattern extraction: if less than 75% of chunks succeed, abort.
- Pattern assignment: same 75% threshold.
- A report based on 85 sessions instead of 100 is usually good enough to find patterns. We surface this in the UI so users know exactly what they're looking at.

### State doesn't fit in memory

Temporal is great for orchestrating complex workflows, but it has limits. Event history size is capped at around 2MB. When you're processing 100 sessions with rich metadata, summaries, and pattern data - you blow past that limit fast. Passing large objects between activities causes the workflow to fail.

**Our approach:**

- Redis as a state bridge. We store all intermediate results (session data, summaries, extracted patterns) in Redis with TTLs, and pass only keys through Temporal.
- Gzip compression before storing. Large JSON summaries compress well, and Redis memory isn't free.
- Clear TTLs (24 hours) so we're not paying for stale data, but long enough to retry failed workflows without re-fetching everything.

**Retries shouldn't redo everything**

A pattern extraction call fails after we've already summarized 100 sessions. Do we start over? That's 100 LLM calls wasted, plus minutes of user wait time. The pipeline has natural checkpoints - we should use them.

**Our approach:**

- Temporal activities are our checkpoints. Each phase (fetch data, summarize sessions, extract patterns, assign events) is a separate activity.
- If pattern extraction fails, we don't re-summarize sessions - we retry from the extraction step using cached summaries.
- Same for video validation - if it fails, the base summary is still saved. We can retry validation separately.

## Step 5: Ship the beta, learn, iterate (We are here) (RAW STEP, EDITING)

We have a pipeline that analyzes single sessions, validates issues with video, extracts patterns across 100 sessions, and survives LLM failures gracefully. It works. But "works" and "done" are different things.

{{ screenshot of the chat interface with session summaries }}
(under the image text) Session summaries is available now in PostHog AI chat - try it on your own sessions

### It's not fast

The honest truth: analyzing 100 sessions takes 5-7 minutes. We wanted 30 seconds. We tried faster models, smaller context windows, aggressive parallelization. The result was either slow or bad, never both fast and good.

**Our approach:**

- We picked quality. A report worth reading in 5 minutes beats a useless report in 30 seconds.
- We show progress as it happens - which sessions are being analyzed, which patterns are emerging - so waiting doesn't feel like staring at a spinner.
- We're exploring background processing for the future: analyze sessions continuously, surface issues proactively, no waiting required.

### It only finds issues

Right now, if you ask "what happened in these sessions?" - we'll tell you what went wrong. We focused on issue detection first: blocking errors, confusion, abandonments. General summarization ("user browsed products, added to cart, checked out successfully") isn't supported yet.

**Our approach:**
- Do one thing well before expanding scope. Issue detection is the highest-value use case - it's what saves hours of manual session review.
- General summarization is coming. The architecture supports it; we just need to tune the prompts and output format.

### What's next

This beta is step one. Here's where we're heading:

- Scale: Thousands of sessions, processed continuously in the background
- Proactive alerts: Issues find you, not the other way around
- Full video understanding: Transcribe entire sessions, not just validation clips
- Beyond Replay: Apply the same pattern extraction to error tracking, LLM traces, support tickets
- Free-text queries: "Find sessions where users looked confused for more than 30 seconds"

The code is open source - you can see exactly how it works, including all the prompts.

## TODO - Ending part  -->
