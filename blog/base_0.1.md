⏺ Based on your feedback, let me refine the direction. Here's my proposed structure:

  ---
  Proposed Title Options

  Primary recommendation:
  "Finding the needle in 10,000 events: multi-modal pattern extraction from user sessions"

  Alternatives:

- "How we taught AI to watch 100 user sessions and find what actually matters"
- "Multi-modal reasoning at scale: from raw session data to actionable patterns"
- "Beyond event logs: combining structured data and video to understand user behavior"

  ---
  Proposed Subtitle/Hook

  "We built an AI feature that analyzes up to 100 user sessions at once, combining thousands of events with video validation to surface patterns that matter. Here's what we learned about multi-modal
  reasoning, token economics, and making LLM pipelines reliable."

  ---
  Article Structure with Illustration Placeholders

  1. The Problem (relatable hook)

  ~300 words

- Open with the universal problem: you have user behavior data, lots of it. Too much to manually review.
- Specific to us: PostHog customers have Session Replay - video recordings of user sessions. Each session can have thousands of events.
- The dream: AI watches sessions for you, surfaces what matters
- The reality: this is surprisingly hard

  [ILLUSTRATION 1: "The scale problem"]
  Simple diagram showing: 100 sessions × 1000s events each = millions of tokens. Add a small visual of a human drowning in data vs. AI assistant surfacing key issues.

  ---

  2. Why events alone aren't enough

  ~400 words

- First attempt: feed events to LLM, ask "what went wrong?"
- Problem: LLMs get panicky about JavaScript errors
- Real insight: many errors in logs don't actually impact users. Early-stage startups spam exceptions constantly.
- The "crying wolf" problem: if every session reports 10 critical issues, nothing is critical

  Key learning: Structured data tells you what happened. It doesn't tell you if it mattered to the user.

  [ILLUSTRATION 2: "Events vs. reality"]
  Side-by-side: Left shows event log with scary red errors. Right shows actual user screen - everything looks fine, user completed their goal. Caption: "The logs said disaster. The user said 'works for
  me.'"

  ---

  3. Adding the visual layer (multi-modal approach)

  ~500 words

- Solution: generate short videos for critical moments, ask LLM to verify
- How it works: 12-second clips, starting 7 seconds before the flagged event
- Key insight: LLMs analyze video at ~1 frame per second, so we render at 8x speed (lighter files, same information density)
- Model choice: Gemini 2.5 Flash for video understanding (fast, good at visual details)
- What we validate: blocking errors, confusion moments, abandonments

  Key learning: Multi-modal validation catches false positives that text-only analysis misses. The cost is worth it for high-severity issues.

  [ILLUSTRATION 3: "Video validation flow"]
  Flow diagram: Event flagged as "blocking error" → Generate 12s video → LLM watches video → Confirms/denies impact → Updates summary. Show a "before/after" of a summary with crossed-out false positive.

  ---

  4. From individual sessions to patterns

  ~600 words

- Single session summaries are useful, but the real value is in patterns across sessions
- The architecture: three-phase extraction
    a. Summarize each session individually (parallel, can tolerate 50% failures)
    b. Extract patterns from summaries (chunked by token limits, deduplicated)
    c. Assign events back to patterns (enrich with context, calculate stats)
- Why chunking matters: 100 sessions × summary size can exceed any model's context
- The deduplication problem: when processing in chunks, you get duplicate patterns. Need a "combine" step.
- Severity calibration: a medium issue in 80% of sessions becomes high priority

  Key learning: Pattern extraction is a multi-stage pipeline, not a single prompt. Each stage has different reliability requirements.

  [ILLUSTRATION 4: "Three-phase pattern extraction"]
  Architecture diagram showing the pipeline: Sessions → [Parallel summarization with video validation] → Summaries → [Chunked pattern extraction] → Raw patterns → [Combination/dedup] → Final patterns →
  [Event assignment] → Enriched report

  ---

  5. Making it reliable with Temporal

  ~500 words

- Problem: we're making 100+ LLM calls per report. Any can fail.
- Solution: Temporal workflows with smart failure handling
- Key patterns:
  - Failure thresholds: if <50% of session summaries succeed, abort. Otherwise, continue with what we have.
  - Redis as state bridge: Temporal has memory limits (~2MB). We store intermediate results in Redis, pass keys through Temporal.
  - Checkpointing: if pattern extraction fails, we don't re-summarize sessions
  - Parallel execution with TaskGroups: speed matters when processing 100 sessions
- Model selection strategy: fast models (GPT-4.1) for streaming single summaries, reasoning models (o3) for pattern extraction

  Key learning: LLMs are unreliable. The infrastructure around them doesn't have to be. Build for partial failure.

  [ILLUSTRATION 5: "Temporal workflow architecture"]
  Simplified workflow diagram showing: Fetch data → Parallel session summaries (with failure tolerance indicator) → Pattern extraction (with chunking) → Final report. Highlight Redis state storage on the
  side.

  ---

  6. Token economics (the boring stuff that matters)

  ~400 words

- Every token costs money and time. At scale, small optimizations compound.
- What we learned:
  - YAML output over JSON: fewer bracket tokens, better structure than markdown
  - URL/window mappings: instead of repeating full URLs, use url_1, url_2 references
  - Simplified event IDs: 8-character hashes instead of full UUIDs (6 tokens vs 52 tokens per event)
  - Skip the first 5 seconds: sessions often start with a burst of initialization events/errors that aren't meaningful
  - Event deduplication: repeated events get single IDs
  - Gzip in Redis: compress large summaries before caching

  Key learning: Token optimization isn't premature optimization when you're processing millions of tokens per report.

  [ILLUSTRATION 6: "Token savings breakdown"]
  Simple bar chart or table showing: "Full UUIDs: 52 tokens/event → Simplified IDs: 6 tokens/event" and similar comparisons. Maybe a "before/after" of a prompt snippet.

  ---

  7. What doesn't work (yet)

  ~350 words

- Realtime summarization: we wanted 20-30 second responses. Not possible with current approach - either use dumber models (bad summaries) or less context (incomplete picture). Current: 5-7 minutes for
  100 sessions.
- Free-form questions: "what happened in this session?" - we focused on issue detection first, not general Q&A
- Full video understanding: we only generate validation videos for flagged moments, not continuous transcription (coming soon)
- Scale beyond 100: current limit is 100 sessions per report. Goal is thousands, with proactive alerting.

  Honest take: This is beta. We chose to do one thing well (find issues) before expanding scope.

  [ILLUSTRATION 7: "Current vs. future capabilities"]
  Simple comparison table or roadmap visual showing: Current (100 sessions, issue detection, 5-7 min) vs. Coming soon (1000s of sessions, proactive alerts, full session Q&A)

  ---

  8. What we're building next

  ~300 words

- Scale to thousands of sessions with proactive issue detection
- Expand beyond Replay: LLM analytics traces, Error tracking, support tickets
- Full-session video understanding (not just validation clips)
- Free-text queries: "find sessions where users stared at UI for 40 seconds confused"

  The vision: Instead of you finding issues, issues find you.

  ---

  9. Try it yourself (CTA)

  ~150 words

- Feature available in beta in PostHog AI chat
- All code is open source (link to repo)
- Mention specific prompts are viewable in the codebase
- Invite feedback

  [SCREENSHOT: The report UI]
  Use the report-ui.png showing patterns with severity, session counts, and the chat interface

  ---
  Key Takeaways Summary (for reader)

  1. Events tell you what, video tells you if it mattered - multi-modal validation catches false positives
  2. Pattern extraction is a pipeline, not a prompt - summarize → extract → combine → assign
  3. Build for partial failure - Temporal + failure thresholds + Redis checkpointing
  4. Token economics compound - YAML, mappings, simplified IDs, compression
  5. Do one thing well first - we focused on issue detection before expanding to general Q&A

  ---
  Questions Before Finalizing

  1. On model specifics: You mentioned "what models we don't use" - should I add a section on why we tried GPT-5 and reverted? Or keep model discussion lighter?
  2. On the "beta" framing: How prominent should the product announcement be? Current structure buries it in CTA. Should there be a more prominent "Announcing: Session Summaries beta" section?
  3. On humor: PostHog articles often have dry humor. Any specific tone you want? The Anthropic articles are more straightforward.
  4. Length check: This structure is ~3,500 words. Too long? The Anthropic articles are ~2,000-2,500. PostHog "8 learnings" was ~2,500.
