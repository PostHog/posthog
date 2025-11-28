# How we built user behavior analysis with multi-modal LLMs in 7 not-so-easy steps

We have tons of user behavior data - what pages they visit, what buttons they click, and so. And by a lot I mean billions of events and terrabytes of stored Replay snapshots. The problem is obvious - there are too many user sessions to watch manually. So, we created a tool to watch them for you and highlight the issues. It's called Session summaries, we release it in beta today, and you can use it right now for free with PostHog AI.

Here I'll list step-by-step what we learned, where we messed up, and lots of practical tips on how to make user behavior analysis to work in production.

## Step 1: "Analyzing a single user session should be easy"

Let's forget about scaling for a moment, and focus just on a single user session - user visited a website or app, navigated a bit, did something useful, and left. The logic seems straightforward - take all the session events, send to LLM, get the summary.

{{ screenshot of the player with the summary }}
> (under the image text) *Here's how you can get a summary of a single session from chat, or Replay player*

However...

### Not all the context is equally useful

Usually, each user-generated event has lots of metadata attached to it. User info, URLs, type of event, CSS selectors, timestamps, and so. In PostHog case, a single session with all the metadata could easily hit a million of tokens. Even if we forget about pricing and context limits, providing too much data will force lost-in-the-middle effect - LLM will provide highlights on what happened at the very start or end, but completely miss the main part.

**Our approach:**

- Start with the "what I need 100%" approach, keeping minimal set of events and fields, adding new ones only if they increase the quality of the summary.
- Mappings for everything. If you event data include URLs - use `url_N` and attach mapping. Same for tab ids, and any repeating parameters.
- Use CSV input. Neither JSON no TOON (heh) will get you the same generation quality per input token.

### Paralellization breaks the story told

If the user spent multiple hours on the website, their session could be huge. If you have lots of such users (like we do), it makes sense to start with splitting such sessions in segments and then analyze each one in parallel improve latency. It's a trap. If LLM doesn't know what happened before or after, it loses a critical context on what the current segment events actually means, so the combined result is worthless.

**Our approach:**

- As stupid as it sounds, just do segmenting and analysis in one very large call, so LLM knows everything.
- If you decide to go with segmenting - go sequential, so when analyzing segment #2, it has context on what happened in segment #1. You will still lose on "what happened next" part and it will be crazy slow though.
- Hope that your users are ok with waiting for a couple of minutes. Using faster models can you results faster, but thinking models on "high" provide better results quality-wise, and quality is the goal.

### Crying wolf effect

Fast-growing products (start-ups specifically) has a bad habbit of generating lots of exceptions, especially frontend ones. LLMs seems them, panicks, and generates a summary of the session where the user completely failed in all their goals. In reality the user successfully got what they came from, and didn't even notice these exceptions.

**Our approach:**

- Programmatically pre-filter events that look like exceptions, especially if one causes multiple others as avalanche and they create a context that LLM can't ignore. For example, drop all JS exceptions that aren't API errors.
- It won't save you anyway.

## Step 2: See what the user sees

...
