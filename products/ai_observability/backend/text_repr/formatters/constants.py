"""
Shared constants for text representation formatters.

Centralizes all magic numbers and configuration values for consistent behavior
across message, tool, text, trace, and span formatters.
"""

# Truncation and display limits
DEFAULT_TRUNCATE_BUFFER = 1000  # Characters to show at start/end when truncating
MAX_UNPARSED_DISPLAY_LENGTH = 500  # Max length for unparsed content display
MAX_UNABLE_TO_PARSE_REPR_LENGTH = 500  # Max length for repr() fallback in error messages

# Uniform sampling for large text representations
# GPT-4.1-mini has 1M token context, but char-to-token ratio varies widely:
# - Simple English text: ~4 chars/token
# - JSON/code/special chars: ~2-3 chars/token (much worse)
# Using 2M chars to safely fit within context even with poor token efficiency.
# At worst case 2:1 ratio: 2M chars = 1M tokens (leaves minimal buffer for prompt/output)
# At typical 2.5:1 ratio: 2M chars = 800K tokens (leaves 200K buffer)
DEFAULT_MAX_LENGTH = 2_000_000
PRESERVE_HEADER_LINES = 5  # Number of header lines to always keep when sampling
SAMPLED_VIEW_HEADER = (
    "[SAMPLED VIEW: Showing ~{percent:.0f}% of {total:,} lines. Gaps in line numbers indicate omitted content.]"
)
# Iterative sampling refinement: initial estimate uses average line length, but sampled
# lines may be longer. These control convergence to fit within max_length.
SAMPLING_MAX_ITERATIONS = 10  # Max refinement iterations (typically converges in 2-3)
SAMPLING_REDUCTION_FACTOR = 0.9  # Safety margin when reducing target line count

# Tool formatting
DEFAULT_TOOLS_COLLAPSE_THRESHOLD = 5  # Collapse tool lists longer than this

# OpenAI Responses API item shapes. Unlike Chat Completions messages, these keep their payload
# outside `content`: tool calls in `arguments` / `input`, tool results in `output`, model
# reasoning in `summary`. A formatter that reads only `content` renders them as a bare header.
RESPONSES_TOOL_CALL_TYPES = frozenset({"function_call", "custom_tool_call"})
RESPONSES_TOOL_OUTPUT_TYPES = frozenset({"function_call_output", "custom_tool_call_output"})
# Rendered in an unrecognized item's signature line, so its payload dump can skip them.
RESPONSES_ITEM_METADATA_KEYS = frozenset(
    {"type", "id", "call_id", "name", "arguments", "input", "status", "encrypted_content"}
)
# Any of these makes a dict a Chat Completions message, not a Responses item.
CHAT_COMPLETIONS_MESSAGE_KEYS = frozenset({"role", "content", "tool_calls"})
# Blocks that are already plain text, so a `[TYPE]` label would only restate them.
PLAIN_TEXT_BLOCK_TYPES = frozenset({"text", "input_text", "output_text", "summary_text"})
# Non-Responses tool blocks with a dedicated renderer in `_format_special_block`.
SPECIAL_BLOCK_TYPES = frozenset({"tool-call", "tool_use", "function"})

# An unrecognized item dumps its own fields, and one of them can be a base64 image or screenshot.
# Capping per field keeps the item's shape readable without pushing megabytes into the trace view,
# where `truncate_content`'s expand marker would otherwise carry the whole value.
MAX_RESPONSES_FIELD_CHARS = 2000
OVERSIZED_FIELD_NOTE = "[{chars:,} chars not shown]"

# Placeholders for evidence the event never carried. Without them a reader, or an LLM judge
# grading the trace, cannot tell a tool that returned nothing from a payload we failed to record.
MISSING_TOOL_OUTPUT_NOTE = "[tool output not recorded]"
MISSING_REASONING_NOTE = "[reasoning summary not recorded]"
MISSING_TOOLS_NOTE = "[tool catalog not recorded]"

# Tree rendering
MAX_TREE_DEPTH = 10  # Maximum depth for hierarchical trace tree rendering

# Visual formatting
SEPARATOR = "-" * 80  # Horizontal separator line for sections
