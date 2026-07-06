import sys
import subprocess


def test_schema_enums_imports_without_loading_schema():
    # posthog.schema_enums exists so enum-only consumers can avoid the ~2s pydantic
    # model build in posthog.schema; a reference back to schema would defeat that.
    code = "import sys, posthog.schema_enums; assert 'posthog.schema' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"schema_enums import pulled in posthog.schema:\n{result.stderr}"
