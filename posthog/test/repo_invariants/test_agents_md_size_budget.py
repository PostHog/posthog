from pathlib import Path

ROOT_AGENTS_MD_BYTE_BUDGET = 23_000


def test_root_agents_md_stays_within_its_byte_budget() -> None:
    size = (Path(__file__).resolve().parents[3] / "AGENTS.md").stat().st_size

    assert size <= ROOT_AGENTS_MD_BYTE_BUDGET, (
        f"AGENTS.md is {size} bytes, over its budget of {ROOT_AGENTS_MD_BYTE_BUDGET}. "
        "Every agent session loads the root file in full, so each byte costs every task in the repo. "
        "Move topic rules to a guide under .agents/ or to a skill, or cut an older line, before you add one. "
        "See /editing-agents-md. Raise the budget only with a reviewer's agreement."
    )
