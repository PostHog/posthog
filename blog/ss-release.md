# Session Summaries PostHog AI feature release - Technical article structure

## Task

- I need your help to propose variants for structure for the technichal article.
- Analyze all the context above, and propose variants of the structure of the acticle that would allow to deliver this context to the target audience.
- Don't write the article itself, just outlier of blocks/headers and what could be inside

### Audience/goal of the article

- The main audience is product engineers and AI engineers
- The goal is to talk about interesting challenge we solved, so the article is educational (priority #1), but also announce a new AI feature
- The story of what failed, what worked, what approach we picked, what works, what will work soon
- Should increase the perception of quality of our AI and the perception of PostHog as an AI-first product
- The article should follow "relatable problem -> solution" logic, but should be interesting to engineers in general, even if they don't watch session
- It should have a "takeaway" readers can apply to their own work
- Balances depth with accessibility

### Similar articles

- Focus on the style of the articles from Antrhopic (https://www.anthropic.com/engineering/advanced-tool-use and https://www.anthropic.com/engineering/code-execution-with-mcp, read them in detail). Focus on technical depth, clear diagrams, honest about limitations.
- But also keep in mind the PostHog style of articles (https://posthog.com/blog/8-learnings-from-1-year-of-agents-posthog-ai and https://posthog.com/newsletter/how-startups-lose-their-edge, also read them in detail). Focus on conversational tone, humor, practical focus, "here's what we learned" framing.

## Feature

### Main pain point/problem -> solution of the feature

- Projects have tons of users that have tons of sessions, so the developers/product managers/etc. can't watch all the sessions
- We want to watch sessions for them and surface the issues, saving them time and highlighting what to improve, needle in the haystack

### Technical challenges

- Sessions could include thousands of events, leading to millions and millions of tokens to get proper context from
- RRWeb files we use for Replay could weight up to 700MB with tens of thousands of mutations
- We need to make it work in a meaningful time (~5-7 minutes), instead of long on-the-background processing
- Without video validation for blocking issues the reports are a bit panicky on JavaScript errors and failed queries, so we need to actually see what the user sees to confirm the issue happened
- Early-stage or fast-growing startups usually spam tens of exceptions and it's an expected user experience, so we need to understand which ones matter

### How does the feature work

The feature is accessible as a tool from PostHog AI chat. You can ask PostHog AI to analyze a single summary, or a group of summaries.

#### Single session summary logic

- We pick events that happened during the session, including clicks, pageviews, exceptions and so
- We split each session into segments and then search issues within this segments - exceptions, abandonments, and confussion
- We then generate a report on the session, that is accessible through PostHog AI chat (you can talk with the report also), or you can check in in detail in Replay player

#### Session group summary logic

- First we analyze each session separarely (single session), feeding events to LLM, and creating single session summaries, accessible from the Replay (user session video) player
- Then, if we surfaced blocking issues in the summary - we generate ~10s videos for each caught blocking issue and transcribe them with LLMs - to validate that the issue actually happened from the user point of view. For example, we can see tons of javascript exceptions in the logs, but on user's side everything find. We then use the transcription to either keep the blocking issue in the summary (if confirmed) or remove/update it (if it didn't actually happen)
- After that, we analyze summaries of single sessions in groups to find repeating patterns
- We then analyze pattern chunks found in groups to deduplicate them and get a final list of patterns
- And as the final step - we iterate over sessions and match the caught issues with the patterns, so we get a tidy list of patterns with examples from multiple sessions
- We then show the report in the UI, allowing to research each pattern and example in detail
- You can also talk with the report in PostHog AI chat window

### Pros/cons

#### What the feature can do now

- Analyze 1-100 Replay sesssions and surface what issues we found inside
- Talk with the generated report to get more context (or instead of using UI)

#### What the feature can't do now

- Answer generic questions on what happened in the session (as we focused ONLY on issues)
- Explain what user sees at the specific moment (as we generate 10s videos only to confirm/deny blocking issues, but not for the whole video; will do that soon though)

### Next plans

- As currently we support report for 100 sessions at once, we plan to scale to thousands, and be proactive - instead of you selecting sessions and searching for issues - we will highlight the issues ourselves and ping you.
- It's the first step, next we'll do the reporting not just using your Replay data, but using your LLM analytics traces, Error tracking issues, Zendesk tickets, and so, signaling you about any new issues proactively, or tracking the trends on known issues.
- The next iteration will allow you to find sessions based on free-text questions ("find me sessions where user stared at UI for 40s not knowing what to do") and focus on that "what users sees" more as we have (in alpha) a solution to do double-side summary - both from the events side and what user sees on their screen side (by doing full-session transcriptions, instead of 10s validation video transcriptions we do now)

## Context

### Main context

- Article is focused on the BETA release of a new feature of our PostHog AI chat assistant, but it should be useful technical article unrelated to the product
- The product is PostHog - web analytics platform, that collects analytics data, record videos of users visiting website, and so
- The AI feature called Session summaries - we take 100 (at the moment) user sessions at once, and "watch" them for user with LLMs - highlighting patterns of issues that we noticed in these sessions. In the end, you can talk with the report
- The focus of the BETA release of the feature is to make a tool that does one thing - surface the issues found in the sessions, so you don't need to watch hundreds of sessions youself. It's not one-fit-all agent yet (but could be soon), but a single focused PostHog AI tool, with a straight direction to solve a single problem well. We'll use it as a basis for other tools for different mediums (LLM analytics, error tracking, Zendesk, user interviews, etc.), so it's the first step.

### Code UI context

- The main interfaces is this node, that spaws Temporal workflows - @ee/hogai/chat_agent/session_summaries/nodes.py
- The UI of the session group report looks like this: @blog/report-ui.png
- The specific example (inside the session group report pattern) looks like this: @blog/single-issue-inside-pattern-ui.png
- The single session summary looks like this in the chat: @blog/single-session-summary-within-chat-ui.png; and like this in the Replay player: @blog/single-sesion-summary-within-player-ui.png

## Notes

### Illustrations

- I plan to add lots of schematic illustrations of logic/approach, as Anthropic does in their articles, and also screenshots of the UI and short GIFs of how the feature looks, used from the PostHog AI chat. It could be Architecture diagrams, UI screenshots, and data flow diagrams.
- Add placeholders where to put illustations and what should be on them

### Suggestions

- All the code is opensource, so it's possible to go and check all our prompts at any time
- The product is in the early stage explicitly, as it has a lots of flaws at the moment

## How to implement

🛑 **MANDATORY WORKFLOW - DO NOT SKIP ANY STEP** 🛑

### Step 1: Understanding phase (REQUIRED - DO NOT SKIP)

- THINK HARDER to analyze the requirements, read ALL attached articles, and ALL attached files thoroughly
- SEARCH through the codebase for additional relevant context
- ASK clarifying questions about anything unclear, any missing context or specifications

### Step 2: Planning phase (ONLY after clarifications)

- Based on clarified requirements, CREATE a high level plan
- NEVER plan changes for backwards compatibility
- PRESENT this plan and WAIT for approval

### Full stop ⚠️ - Do NOT write any code until:

- ALL questions have been answered
- Your plan has been REVIEWED
- You receive explicit "proceed" CONFIRMATION

### Step 3: Implementation phase (ONLY after explicit approval)

- EXECUTE the approved plan
- REPORT any deviations immediately
- ASK before making unexpected changes
