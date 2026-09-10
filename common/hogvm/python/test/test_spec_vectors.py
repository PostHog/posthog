import json
from pathlib import Path
from typing import Any

import pytest

from common.hogvm.python.execute import execute_bytecode

VECTORS_DIR = Path(__file__).parents[2] / "spec" / "vectors"


def _cases() -> list[Any]:
    cases = []
    for path in sorted(VECTORS_DIR.glob("*.json")):
        for case in json.loads(path.read_text())["cases"]:
            if "python" in case["implementations"]:
                cases.append(pytest.param(case, id=case["name"]))
    return cases


@pytest.mark.parametrize("case", _cases())
def test_spec_vector(case: dict[str, Any]) -> None:
    if "error" in case["expect"]:
        with pytest.raises(Exception) as e:
            execute_bytecode(case["bytecode"], {})
        assert str(e.value) == case["expect"]["error"]
    else:
        assert execute_bytecode(case["bytecode"], {}).result == case["expect"]["result"]
