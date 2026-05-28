"""Search for a keyword across all event properties in a trace."""

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


def search_obj(obj, term, path=""):
    if isinstance(obj, str):
        if term in obj.lower():
            idx = obj.lower().index(term)
            start, end = max(0, idx - 80), min(len(obj), idx + len(term) + 80)
            yield path, obj[start:end]
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from search_obj(v, term, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from search_obj(v, term, f"{path}[{i}]")


term = os.environ.get("SEARCH", "").lower()
if not term:
    print("Usage: SEARCH='keyword' python3 search.py file.json", file=sys.stderr)
    sys.exit(1)

traces = load_trace_file(sys.argv[1])
for trace in traces:
    for ev in trace.get("events", []):
        p = ev.get("properties", {})
        name = p.get("$ai_span_name", p.get("$ai_model", ev.get("event", "?")))
        for path, snippet in search_obj(p, term):
            print(f"\n[{ev.get('createdAt', '?')}] {name} -> {path}")
            print(f"  ...{snippet}...")
