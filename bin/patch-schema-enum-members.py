from pathlib import Path

SCHEMA_PATH = Path("posthog/schema.py")
TARGET_CLASSES = {"AgentMode", "ProductKey"}
OLD_MEMBER = '    LLM_ANALYTICS = "llm_analytics"'
NEW_MEMBER = '    AI_OBSERVABILITY = "llm_analytics"'


def main() -> None:
    lines = SCHEMA_PATH.read_text().splitlines()
    current_class: str | None = None
    patched_lines: list[str] = []

    for line in lines:
        if line.startswith("class "):
            current_class = line.split("class ", 1)[1].split("(", 1)[0]

        if current_class in TARGET_CLASSES and line == OLD_MEMBER:
            patched_lines.append(NEW_MEMBER)
            continue

        patched_lines.append(line)

    new_content = "\n".join(patched_lines) + "\n"
    old_content = SCHEMA_PATH.read_text()
    if new_content == old_content:
        return

    SCHEMA_PATH.write_text(new_content)


if __name__ == "__main__":
    main()
