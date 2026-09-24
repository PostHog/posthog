import difflib
from collections.abc import Callable
from typing import Any

from posthog.dataclasses import frozen

from products.canvas.backend.source import diagnostic

_NO_MATCH_EXCERPT_LINES = 5
_MAX_COMPARED_LINE_CHARS = 200


@frozen
class EditProblem:
    code: str
    message: str
    line: int | None


def apply_source_edits(
    project: dict[str, Any], operations: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    files = dict(project["files"])
    diagnostics: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        problem = _apply_source_edit(files, operation, index)
        if problem is not None:
            diagnostics.append(problem)
    return {**project, "files": files}, diagnostics


def _apply_source_edit(files: dict[str, str], operation: dict[str, Any], index: int) -> dict[str, Any] | None:
    kind = operation["op"]
    path = operation["path"]
    if kind == "write":
        files[path] = operation["content"]
        return None
    if path not in files:
        return diagnostic(
            "error", "edit_target_missing", f"operation {index}: the project has no file at {path}", path=path
        )
    if kind == "delete":
        del files[path]
        return None
    if kind == "rename":
        new_path = operation["new_path"]
        if new_path in files:
            return diagnostic(
                "error",
                "edit_target_exists",
                f"operation {index}: cannot rename {path} to {new_path} because a file already exists there",
                path=path,
            )
        files[new_path] = files.pop(path)
        return None
    result = _replace_in_file(
        files[path], operation["old_string"], operation["new_string"], replace_all=operation.get("replace_all", False)
    )
    if isinstance(result, EditProblem):
        return diagnostic("error", result.code, f"operation {index}: {result.message}", path=path, line=result.line)
    files[path] = result
    return None


def _replace_in_file(text: str, old: str, new: str, *, replace_all: bool) -> str | EditProblem:
    count = text.count(old)
    if count == 1 or (count > 1 and replace_all):
        return text.replace(old, new)
    if count > 1:
        lines = _exact_match_lines(text, old)
        return EditProblem(
            code="edit_ambiguous_match",
            message=f"old_string matches {count} places (lines {', '.join(map(str, lines[:5]))}). "
            "Include more surrounding lines to make it unique, or set replace_all to replace every match.",
            line=lines[0],
        )
    if not replace_all:
        eol = "\r\n" if "\r\n" in text else "\n"
        file_lines = text.split(eol)
        old_lines = _edit_lines(old)
        if any(line.strip() for line in old_lines):
            for normalize in (str.rstrip, str.strip):
                starts = _loose_match_starts(file_lines, old_lines, normalize)
                if len(starts) == 1:
                    start = starts[0]
                    matched = file_lines[start : start + len(old_lines)]
                    file_lines[start : start + len(old_lines)] = _reindent(_edit_lines(new), old_lines, matched)
                    return eol.join(file_lines)
                if len(starts) > 1:
                    return EditProblem(
                        code="edit_ambiguous_match",
                        message=f"old_string matches {len(starts)} places when whitespace is ignored "
                        f"(lines {', '.join(str(start + 1) for start in starts[:5])}). "
                        "Include more surrounding lines to make it unique.",
                        line=starts[0] + 1,
                    )
    return _no_match_problem(text, old)


def _edit_lines(value: str) -> list[str]:
    lines = value.replace("\r\n", "\n").split("\n")
    if len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return lines


def _exact_match_lines(text: str, old: str) -> list[int]:
    lines: list[int] = []
    position = text.find(old)
    while position != -1:
        lines.append(text.count("\n", 0, position) + 1)
        position = text.find(old, position + max(len(old), 1))
    return lines


def _loose_match_starts(file_lines: list[str], old_lines: list[str], normalize: Callable[[str], str]) -> list[int]:
    target = [normalize(line) for line in old_lines]
    normalized = [normalize(line) for line in file_lines]
    width = len(target)
    return [start for start in range(len(normalized) - width + 1) if normalized[start : start + width] == target]


def _reindent(new_lines: list[str], old_lines: list[str], matched_lines: list[str]) -> list[str]:
    old_indent = _indent_of(next((line for line in old_lines if line.strip()), ""))
    file_indent = _indent_of(next((line for line in matched_lines if line.strip()), ""))
    if file_indent.startswith(old_indent):
        extra = file_indent[len(old_indent) :]
        return [extra + line if line.strip() else line for line in new_lines]
    if old_indent.startswith(file_indent):
        surplus = old_indent[len(file_indent) :]
        return [line[len(surplus) :] if line.startswith(surplus) else line for line in new_lines]
    return new_lines


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _no_match_problem(text: str, old: str) -> EditProblem:
    anchor = next((line.strip() for line in old.splitlines() if line.strip()), "")
    file_lines = text.splitlines()
    if not anchor or not file_lines:
        return EditProblem(code="edit_no_match", message="old_string was not found in the file.", line=None)
    best = max(
        range(len(file_lines)),
        key=lambda index: difflib.SequenceMatcher(
            None, anchor[:_MAX_COMPARED_LINE_CHARS], file_lines[index].strip()[:_MAX_COMPARED_LINE_CHARS]
        ).ratio(),
    )
    excerpt = "\n".join(
        f"{number + 1}: {file_lines[number][:_MAX_COMPARED_LINE_CHARS]}"
        for number in range(best, min(best + _NO_MATCH_EXCERPT_LINES, len(file_lines)))
    )
    return EditProblem(
        code="edit_no_match",
        message=f"old_string was not found in the file. The closest text starts at line {best + 1}:\n{excerpt}",
        line=best + 1,
    )
