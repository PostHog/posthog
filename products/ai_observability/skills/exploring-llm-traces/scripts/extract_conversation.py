"""Extract user/assistant messages from LLM generation events in a trace.

Env vars:
  MAX_LEN  — truncation limit per message (default 500, 0 for unlimited)
"""

import json
import os
import sys


def load_trace_file(path):
    with open(path) as f:
        raw = json.load(f)
    # Claude Code persists large MCP tool results as [{"type": "text", "text": "<json>"}] — unwrap to get the actual trace data.
    if isinstance(raw, list) and raw and raw[0].get("type") == "text":
        raw = json.loads(raw[0]["text"])
    # Both query-llm-trace and query-llm-traces-list return {"results": [...]}, but handle a bare trace object too.
    results = raw.get("results", raw)
    return [results] if isinstance(results, dict) else results


def truncate(text, max_len):
    if max_len <= 0 or len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f"\n  ... [{len(text)} chars] ...\n  " + text[-half:]


def format_content(content, max_len):
    """Format message content, preserving thinking/text/tool_use structure."""
    if isinstance(content, str):
        return truncate(content, max_len)
    if not isinstance(content, list):
        return str(content)

    parts = []
    for item in content:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        item_type = item.get("type", "")
        if item_type == "thinking":
            thinking = item.get("thinking", "")
            parts.append(f"  [thinking] {truncate(thinking, max_len)}")
        elif item_type == "text":
            parts.append(f"  {truncate(item.get('text', ''), max_len)}")
        elif item_type == "tool_use":
            name = item.get("name", "?")
            tool_input = json.dumps(item.get("input", {}), default=str)
            parts.append(f"  [tool_use: {name}] {truncate(tool_input, max_len)}")
        elif item_type == "tool_result":
            tool_id = item.get("tool_use_id", "?")
            result_content = item.get("content", "")
            if isinstance(result_content, list):
                result_content = " ".join(
                    p.get("text", "") for p in result_content if isinstance(p, dict)
                )
            parts.append(f"  [tool_result: {tool_id}] {truncate(str(result_content), max_len)}")
        else:
            parts.append(f"  [{item_type}] {truncate(json.dumps(item, default=str), max_len)}")
    return "\n".join(parts)


max_len = int(os.environ.get("MAX_LEN", "500"))

traces = load_trace_file(sys.argv[1])
for trace in traces:
    for ev in sorted(trace.get("events", []), key=lambda e: e.get("createdAt", "")):
        if ev.get("event") != "$ai_generation":
            continue
        p = ev.get("properties", {})
        messages = p.get("$ai_input")
        if not isinstance(messages, list):
            continue
        model = p.get("$ai_model", "?")
        print(f"\n{'='*80}")
        print(f"Generation: {model}  ({ev.get('createdAt', '?')})")
        print(f"{'='*80}")
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")

            # Show tool_calls on assistant messages
            tool_calls = msg.get("tool_calls", [])

            print(f"\n[{role.upper()}]")
            print(format_content(content, max_len))

            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", tc)
                    name = fn.get("name", "?")
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        args_str = args
                    else:
                        args_str = json.dumps(args, default=str)
                    print(f"  [tool_call: {name}] {truncate(args_str, max_len)}")

        # Show output choices
        choices = p.get("$ai_output_choices", [])
        if choices:
            print(f"\n[ASSISTANT (output)]")
            for choice in choices:
                print(format_content(choice.get("content", ""), max_len))
