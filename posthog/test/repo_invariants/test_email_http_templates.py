import ast
from pathlib import Path

import posthog as posthog_pkg
from posthog.email import WORKFLOWS_TEMPLATE_ID_MAP


def test_all_http_templates_are_registered_in_workflows_map() -> None:
    posthog_root = Path(posthog_pkg.__file__).parent
    sources = sorted(
        p
        for p in posthog_root.rglob("*.py")
        if "/test/" not in str(p) and "/tests/" not in str(p) and not p.name.startswith("test_")
    )

    missing: dict[str, str] = {}  # template_name -> first source path that uses it
    for source_path in sources:
        text = source_path.read_text()
        if "EmailMessage" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "EmailMessage"):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
            use_http = kwargs.get("use_http")
            if not (isinstance(use_http, ast.Constant) and use_http.value is True):
                continue
            template_name = kwargs.get("template_name")
            if isinstance(template_name, ast.Constant) and isinstance(template_name.value, str):
                if template_name.value not in WORKFLOWS_TEMPLATE_ID_MAP:
                    missing.setdefault(template_name.value, str(source_path.relative_to(posthog_root.parent)))

    assert missing == {}, (
        "These template_name values use use_http=True in production code but are missing "
        "from WORKFLOWS_TEMPLATE_ID_MAP in posthog/email.py. Add a map entry pointing to "
        "the Workflows message template ID, otherwise the sender will raise "
        "'Unknown template name' at runtime and capture_exception will swallow it."
    )
