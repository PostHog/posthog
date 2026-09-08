from common.hogvm.spec.report import render_report

BASE = {
    "functions": {
        "lower": {"minArgs": 1, "maxArgs": 1},
        "concat": {"minArgs": 1, "maxArgs": None},
        "run": {"minArgs": 1, "maxArgs": 1, "implementations": ["python"]},
    }
}


def test_report_is_empty_when_the_contract_is_unchanged() -> None:
    assert render_report(BASE, BASE) == ""


def test_report_lists_added_removed_and_changed_functions() -> None:
    head = {
        "functions": {
            "lower": {"minArgs": 1, "maxArgs": 2},
            "upper": {"minArgs": 1, "maxArgs": 1},
            "run": {"minArgs": 1, "maxArgs": 1, "implementations": ["python"]},
        }
    }

    report = render_report(BASE, head)

    assert "| `upper` | added | | 1 arg (all VMs) |" in report
    assert "| `concat` | removed | 1+ args (all VMs) | |" in report
    assert "| `lower` | changed | 1 arg (all VMs) | 1-2 args (all VMs) |" in report
    assert "`run`" not in report
