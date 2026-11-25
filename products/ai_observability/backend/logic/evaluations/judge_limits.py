# Char budget for the judge transcript. The shared formatter defaults to ~2M chars (sized to
# fill an LLM context window for summarization); a per-trace judge verdict doesn't need that
# much, so we cap lower to bound cost. Over budget, the formatter uniformly samples lines.
JUDGE_TRACE_MAX_CHARS = 300_000

# A judge model whose context window rejects the full budget gets a transcript cut to this size
# instead of a skip, so a small-context judge still grades every trace it graded before.
JUDGE_TRACE_FALLBACK_MAX_CHARS = 150_000

# Sessions run ~3.5x a trace at p90 (222 events against a trace's typical handful) and the shared
# formatter uniformly samples lines rather than truncating, so a trace-sized budget would hand
# the judge a shredded transcript. 500k chars is ~2.2k chars per event at p90.
JUDGE_SESSION_MAX_CHARS = 500_000
