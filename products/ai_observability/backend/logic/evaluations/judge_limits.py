from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Char budget for the judge transcript. The shared formatter defaults to ~2M chars (sized to
# fill an LLM context window for summarization); a per-trace judge verdict doesn't need that
# much, so we cap lower to bound cost. Over budget, the formatter uniformly samples lines.
JUDGE_TRACE_MAX_CHARS: int = settings.LLMA_JUDGE_TRACE_MAX_CHARS

# A judge model whose context window rejects the full budget gets a transcript cut to this size
# instead of a skip, so a small-context judge still grades every trace it graded before.
JUDGE_TRACE_FALLBACK_MAX_CHARS = 150_000

if JUDGE_TRACE_MAX_CHARS < JUDGE_TRACE_FALLBACK_MAX_CHARS:
    # A smaller budget cuts transcripts the judge graded whole before, and 0 turns off the formatter's sampling.
    raise ImproperlyConfigured(
        f"LLMA_JUDGE_TRACE_MAX_CHARS must be at least {JUDGE_TRACE_FALLBACK_MAX_CHARS}, got {JUDGE_TRACE_MAX_CHARS}"
    )

# Sessions run ~3.5x a trace at p90 (222 events against a trace's typical handful) and the shared
# formatter uniformly samples lines rather than truncating, so a trace-sized budget would hand
# the judge a shredded transcript. 500k chars is ~2.2k chars per event at p90.
JUDGE_SESSION_MAX_CHARS = 500_000
