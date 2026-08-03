"""Measure PR description prose against the mechanically checkable ASD-STE100 writing rules.

Regenerates every figure in pr-description-voice-ste.md.

    gh pr list --author @me --state merged --limit 60 --json number,title,url,body > prs.json
    python3 docs/internal/pr-description-voice-ste-measure.py prs.json

Passive-voice and -ing detection are regex heuristics. They indicate scale, not exact counts.
Approved-word conformance is not measured: the STE dictionary is licensed and cannot be vendored here.
"""

import re
import sys
import json
import statistics
from collections import Counter

FENCE = re.compile(r"```.*?```", re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
HEADING = re.compile(r"^#{1,6} .*$", re.M)
CHECKBOX = re.compile(r"^\s*-\s*\[[ x]\].*$", re.M)
ALERT = re.compile(r"^>\s*\[!\w+\]\s*$", re.M)
FOOTER = re.compile(r"\*Created with \[PostHog Code\].*", re.S)
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
INLINE_CODE = re.compile(r"`[^`]*`")

ABBREV = ("e.g", "i.e", "vs", "etc", "approx", "No", "min", "sec", "Inc")
SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'`(])")
WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")

BE = r"\b(is|are|was|were|be|been|being|gets?|got)\b"
PASSIVE = re.compile(
    BE + r"\s+(\w+ed|written|run|done|kept|left|built|sent|read|set|put|made|taken"
    r"|given|shown|seen|held|drawn|known|caught|found)\b",
    re.I,
)
ING = re.compile(r"\b(\w{4,}ing)\b", re.I)
# -ing spellings that are ordinary nouns or technical names, not the verb form STE bans
ING_ALLOWED = {
    "anything",
    "bring",
    "ceiling",
    "during",
    "engineering",
    "evening",
    "everything",
    "king",
    "landing",
    "logging",
    "meaning",
    "morning",
    "nothing",
    "reporting",
    "ring",
    "setting",
    "settings",
    "sharding",
    "sibling",
    "siblings",
    "something",
    "spring",
    "string",
    "strings",
    "thing",
    "things",
    "timing",
    "tracing",
    "warning",
    "warnings",
    "willing",
}

# STE substitutions that already match this repo's house style, plus filler STE deletes.
SUBSTITUTIONS = {
    "leverage": "use",
    "utilize": "use",
    "surface": "show",
    "delve": "examine",
    "robust": "strong",
    "seamless": "smooth",
    "holistic": "complete",
    "myriad": "many",
    "obtain": "get",
    "perform": "do",
    "commence": "start",
    "terminate": "stop",
    "prior to": "before",
    "in order to": "to",
    "via": "with",
    "roughly": "about",
    "basically": "",
    "essentially": "",
    "actually": "",
    "simply": "",
    "just": "",
    "obviously": "",
    "clearly": "",
    "note that": "",
    "kick off": "start",
    "spin up": "start",
    "nuke": "delete",
    "blow up": "fail",
    "shadow": "hide",
    "burn": "use",
    "float": "change",
    "strand": "isolate",
    "collapse": "remove",
    "pare back": "reduce",
    "dead end": "stop",
}

PROCEDURAL_LIMIT = 20
DESCRIPTIVE_LIMIT = 25


def prose(body: str) -> str:
    """Drop everything a prose rule cannot fairly judge: code, mermaid, tables, headings, checkboxes."""
    text = FOOTER.sub("", body)
    for pattern in (FENCE, HTML_COMMENT, TABLE_ROW, HEADING, CHECKBOX, ALERT):
        text = pattern.sub("", text)
    text = MD_LINK.sub(r"\1", text)
    text = INLINE_CODE.sub("CODE", text)
    text = re.sub(r"^\s*[->*]\s+", "", text, flags=re.M)
    return re.sub(r"[*_]{1,2}", "", text)


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in (p.strip() for p in text.split("\n")):
        if not para:
            continue
        merged: list[str] = []
        for part in SENT_END.split(para):
            tail = merged[-1].rstrip().rsplit(" ", 1)[-1].rstrip(".") if merged else ""
            if merged and tail.endswith(ABBREV):
                merged[-1] += " " + part
            else:
                merged.append(part)
        out.extend(s.strip() for s in merged if len(s.split()) >= 3)
    return out


def scan(body: str) -> dict | None:
    text = prose(body)
    sents = sentences(text)
    lengths = [len(WORD.findall(s)) for s in sents]
    if not lengths:
        return None
    lowered = text.lower()
    return {
        "sentences": len(sents),
        "words": sum(lengths),
        "mean": statistics.mean(lengths),
        "max": max(lengths),
        "over_procedural": sum(1 for n in lengths if n > PROCEDURAL_LIMIT),
        "over_descriptive": sum(1 for n in lengths if n > DESCRIPTIVE_LIMIT),
        "passive": sum(len(PASSIVE.findall(s)) for s in sents),
        "ing": [w for s in sents for w in ING.findall(s) if w.lower() not in ING_ALLOWED],
        "substitutions": sorted(w for w in SUBSTITUTIONS if re.search(rf"\b{re.escape(w)}\b", lowered)),
        "longest": sents[lengths.index(max(lengths))],
    }


def main(path: str) -> None:
    prs = json.loads(open(path).read())
    rows = []
    for pr in prs:
        result = scan(pr["body"])
        if result:
            rows.append(result | {"number": pr["number"], "title": pr["title"]})

    chars = sum(len(pr["body"]) for pr in prs)
    code = sum(len(m) for pr in prs for m in FENCE.findall(pr["body"]))
    table = sum(len(m) for pr in prs for m in TABLE_ROW.findall(pr["body"]))
    total_s = sum(r["sentences"] for r in rows)
    total_w = sum(r["words"] for r in rows)

    print(
        f"PRs {len(rows)}   body chars {chars:,}   code+mermaid {100 * code / chars:.0f}%   tables {100 * table / chars:.0f}%"
    )
    print(f"prose sentences {total_s}   prose words {total_w:,}   mean {total_w / total_s:.1f} words/sentence")
    for label, key, limit in (
        ("procedural", "over_procedural", PROCEDURAL_LIMIT),
        ("descriptive", "over_descriptive", DESCRIPTIVE_LIMIT),
    ):
        n = sum(r[key] for r in rows)
        print(f"over {limit} words ({label} limit): {n} ({100 * n / total_s:.0f}%)")
    print(f"passive-voice hits: {sum(r['passive'] for r in rows)}")
    ings = [w.lower() for r in rows for w in r["ing"]]
    print(f"-ing verb forms: {len(ings)} ({len(set(ings))} distinct)")
    clean = sum(1 for r in rows if not r["over_procedural"] and not r["passive"] and not r["ing"])
    print(f"PRs clean on length, voice and -ing: {clean}")

    worst = max(rows, key=lambda r: r["max"])
    print(f"\nlongest sentence: PR {worst['number']}, {worst['max']} words\n  {worst['longest']}")

    print("\nmost common -ing forms:")
    for word, n in Counter(ings).most_common(8):
        print(f"  {word:<12} {n}")

    print("\nsubstitutions, by PRs containing the word:")
    for word, n in Counter(w for r in rows for w in r["substitutions"]).most_common(12):
        print(f"  {word:<12} {n:>3} PRs -> {SUBSTITUTIONS[word] or '(delete)'}")

    print("\nworst offenders:")
    for r in sorted(rows, key=lambda r: -r["over_procedural"])[:8]:
        print(
            f"  {r['number']:>6} {r['over_procedural']:>3} long  {r['passive']:>3} passive  {len(r['ing']):>3} -ing  {r['title'][:50]}"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "prs.json")
