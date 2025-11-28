# How we built user behavior analysis with multi-modal LLMs in 5 not-so-easy steps

We have tons of user behavior data - what pages they visit, what buttons they click, and so, stored as sessions. And by tons I mean billions of events and terabytes of stored Replay snapshots. The problem is obvious - there are too many user sessions to watch manually. So, we created a tool to watch them for you and highlight the issues. It's called Session summaries, we release it in beta today, and you can use it right now for free with PostHog AI.

Here I'll list step-by-step what we learned, where we messed up, and lots of practical tips on how to make user behavior analysis to work in production.

> The steps below assume that you use (or develop) a user behavior analytics service (like PostHog, Hotjar, Microsoft Clarity, and similar), so you have access to user-generated events, and recordings of what the user did on your website.

## Step 1: "Analyzing a single user session should be easy"

Let's forget about scaling for a moment, and focus just on a single user session - user visited a website or app, navigated a bit, did something useful, and left. The logic seems straightforward - take all the session events, send to LLM, get the summary.

{{ screenshot of the player with the summary }}
> (under the image text) *Here's how you can get a summary of a single session from chat, or Replay player*

However...

{{ TODO: Put a schema somewhere here? What to show though? Multiple types of events as input? }}

### Not all the context is equally useful

Usually, each user-generated event has lots of metadata attached to it. User info, URLs, type of event, CSS selectors, timestamps, and so. In PostHog case, a single session with all the metadata could easily hit a million of tokens. Even if we forget about pricing and context limits, providing too much data will force lost-in-the-middle effect - LLM will provide highlights on what happened at the very start or end, but completely miss the main part.

**Our approach:**

- We start with the "what I need 100%" approach, keeping minimal set of events and fields, adding new ones only if they increase the quality of the summary.
- Mappings for everything. If event data includes URLs - we use `url_N` alias and attach mapping. Same for tab ids, and any repeating parameters.
- CSV input. Neither JSON no TOON (heh) will provide the same generation quality per input token.

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

Even if we found great way to reduce noise, the core problem remained - we can't be sure if the issues that LLM highlighted actually impacted users. We can see TypeError in logs, but the retry happened in 200ms, so it didn't affect the user journey one beat. But what if we generate a video of the session? Then we can see what the user saw clearly, without a need to guess.

{{ scheme/graph of the video validation logic }}
> (under the image text) *For each blocking issue, we generate a short video clip and ask the multi-modal LLM to verify what actually happened*

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

At the first glance, transcribing all the user session videos seems like a no-brainer. For example, Gemini Flash multi-modal models cost 10-20 times cheaper than frontier thinking LLMs from Anthropic or OpenAI (or even Gemini's own thinking models). It can go even lower with open-source models. And it provides a proper transcription what the user sees (most of the time, at least).

However, let's try basic math, using numbers from now (end of 2025). One frame of video in a good-enough resolution costs 258 tokens of Gemini Flash. If `1 frame per second * 60 seconds in a minute * 60 minutes in a hour * 258 tokens = 929k tokens`. Meaning, we analyzed just 1 large-ish session, but already used a million tokens. We can use even ligher models and even worse resolution, but at some moment the quality drop is too much.

Another downside, if that these models are this cheap not because of magic, but because they aren't exactly clever. We can ask it to transcribe what's on the screen well enough, but it won't be able to make meaningful conclusions, like a proper thinking model will do. So, either we need to use way more expensive model from the start, or we need another model to analyze transcription after that.

**Our approach:**

- Don't analyze the whole video - there are at least 40-50-60% of inactivity that we can skip, and pay to transcribe only parts where the user did something. Though, we need either events or snapshots to find these parts.
- Don't analyze all the videos - there's a clear set of parameters (like event count, active duration) that can be used to decide if it's worthwhile to check the session

### Videos are still heavy

Even with all the optimizations above, the videos are still media files. For example, if we decide to highlight important moments of sessions in UI, as GIFs, then even a 10s GIF could weigh up to 7-10MB (if 1080p session). And there are hundreds of thousands of sessions that need to be stored somewhere after a generation. If we would decide to go through with this GIF idea it would mean multiple terabytes of media files to store/manage/pay for on S3 every day.

The example is obviously laughable, but even with regular `.mp4` format (tens of times smaller) it easy to get to terabytes pretty fast.

**Our approach:**

- We use `.webm`. It's roughly half size of the `.mp4`, supported by most multi-modal models, and can be played by most browsers by default (in UI or not).
- We render videos at 8-10x - as I mentioned above, 1 frame per second is usually enough for LLM to understand the context well. However, keep in mind that libraries for recording videos (like `puppeteer` or `playwright`) have different keyframe settings, so after some point speed up will mean the data loss.
