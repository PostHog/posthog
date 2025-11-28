 ---

  0. Introduction + Beta Announcement

  ~250 words

- Lead with the announcement: Session Summaries is now in beta in PostHog AI
- What it does: analyzes up to 100 session recordings at once, surfaces issue patterns
- The problem it solves: too many sessions to watch manually, needle-in-haystack
- Framing: here's how we built it, step by step, from naive first attempt to current architecture
- Note: all code is open source

  [ILLUSTRATION 0: "Session Summaries beta announcement"]
  Screenshot of the report UI (report-ui.png) with a brief caption showing what the feature looks like in practice

  ---
  Step 1: Just call the LLM on a single session

  ~350 words

- The naive approach: feed session events to LLM, ask "summarize this"
- Problem #1: sessions have thousands of events = millions of tokens
- Problem #2: LLM gets panicky about JavaScript errors, reports everything as critical
- Problem #3: early-stage startups spam exceptions constantly - it's expected, not a bug
- Result: summaries that cry wolf, every session looks broken

  Key learning: Structured event data tells you what happened, not if it mattered.

  [ILLUSTRATION 1: "The crying wolf problem"]
  Side-by-side: event log with scary errors vs. actual user screen showing everything works fine

  ---
  Step 2: Add video validation for critical moments

  ~400 words

- Solution: for flagged blocking issues, generate a short video clip and ask LLM to verify
- How it works: 12-second clips, starting 7 seconds before the flagged event
- Key insight: LLMs analyze at ~1 frame per second, so we render at 8x speed
- Model choice: Gemini 2.5 Flash for video understanding
- What we validate: blocking errors, confusion, abandonments
- Result: false positives caught, summaries become trustworthy

  Key learning: Multi-modal validation is worth the cost for high-severity issues.

  [ILLUSTRATION 2: "Video validation flow"]
  Flow diagram: Event flagged → Generate 12s video → LLM watches → Confirms/denies → Updates summary

  ---
  Step 3: Optimize token economics

  ~350 words

- At scale, every token costs money and time
- What we learned:
  - YAML output over JSON (fewer brackets)
  - URL/window_id mappings instead of repeating full strings
  - Simplified event IDs: 8-char hashes vs full UUIDs (6 vs 52 tokens per event)
  - Skip first 5 seconds (initialization noise)
  - Gzip compression in Redis cache
- Why this matters: we're processing millions of tokens per report

  Key learning: Token optimization compounds. Small savings × thousands of events = significant impact.

  [ILLUSTRATION 3: "Token savings"]
  Simple comparison: before/after token counts for a typical session

  ---
  Step 4: Scale to multiple sessions with pattern extraction

  ~500 words

- Single session summaries are useful, but patterns across sessions are the real value
- The three-phase architecture:
    a. Summarize each session individually (parallel)
    b. Extract patterns from summaries (chunked by token limits)
    c. Assign events back to patterns (enrich with context)
- Why chunking: 100 sessions can exceed any model's context window
- The deduplication problem: processing in chunks creates duplicate patterns
- Severity calibration: medium issue in 80% of sessions = high priority

  Key learning: Pattern extraction is a multi-stage pipeline, not a single prompt.

  [ILLUSTRATION 4: "Three-phase pattern extraction"]
  Architecture diagram: Sessions → Parallel summaries → Chunked extraction → Dedup/combine → Event assignment → Report

  ---
  Step 5: Make it reliable with Temporal

  ~450 words

- Problem: 100+ LLM calls per report, any can fail
- Solution: Temporal workflows with smart failure handling
- Key patterns:
  - Failure thresholds: <50% session success = abort, otherwise continue
  - Redis as state bridge: Temporal has ~2MB limit, store intermediate results externally
  - Checkpointing: failed pattern extraction doesn't re-summarize sessions
  - Parallel execution with TaskGroups
- Model selection: fast models (GPT-4.1) for streaming, reasoning models (o3) for pattern extraction
- Why not GPT-5: tried it, reverted - fails to understand complex inputs at low thinking, too slow at high

  Key learning: LLMs are unreliable. The infrastructure around them doesn't have to be.

  [ILLUSTRATION 5: "Temporal workflow architecture"]
  Workflow diagram with failure tolerance indicators and Redis state storage

  ---
  Step 6: Ship the beta (and accept current limitations)

  ~350 words

- What works now:
  - Analyze 1-100 sessions, surface issue patterns
  - Talk with the report in PostHog AI chat
  - Video-validated blocking issues
- What doesn't work yet:
  - Realtime (5-7 minutes, not 30 seconds)
  - Free-form questions ("what happened?" vs "what went wrong?")
  - Full video understanding (only validation clips, not continuous)
  - Scale beyond 100 sessions
- Why we shipped anyway: one thing done well > many things done poorly

  Key learning: Focus beats scope. Issue detection first, expand later.

  [ILLUSTRATION 6: "Current capabilities"]
  The single-issue-inside-pattern-ui.png showing the detail view with video context

  ---
  Step 7: What's next

  ~300 words

- Scale to thousands of sessions with proactive alerting
- Full-session video understanding (not just validation clips)
- Free-text queries: "find sessions where users looked confused for 40+ seconds"
- Beyond Replay: LLM analytics traces, Error tracking, support tickets
- The vision: issues find you, not the other way around

  [ILLUSTRATION 7: "Roadmap"]
  Simple visual: Current (100 sessions, issue detection) → Next (1000s, proactive, multi-source)

  ---
  Closing: Try it + key takeaways

  ~200 words

- Available now in PostHog AI chat (beta)
- All code open source - link to repo, prompts are in the codebase
- Summary of 7 learnings:
    a. Events alone aren't enough
    b. Multi-modal validation catches false positives
    c. Token economics compound
    d. Pattern extraction is a pipeline
    e. Build for partial failure
    f. Focus beats scope
    g. Ship, learn, iterate

  [SCREENSHOT: Chat interface]
  The single-session-summary-within-chat-ui.png showing how to access the feature

  ---
  Total: ~3,150 words + illustrations

  Ready to go block by block when you are.
