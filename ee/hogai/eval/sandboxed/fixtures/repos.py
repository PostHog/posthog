from __future__ import annotations

import tempfile
import subprocess
from pathlib import Path


def create_temp_repo(files: dict[str, str], *, commit_message: str = "initial commit") -> Path:
    """Create a temporary git repository with the given files.

    Args:
        files: Mapping of relative file path → file content.
        commit_message: Message for the initial commit.

    Returns:
        Path to the temporary directory containing the git repo.
        The caller is responsible for cleanup (or let the OS handle it via tempdir).

    Example::

        repo = create_temp_repo({
            "main.py": "def add(a, b):\\n    return a + b\\n",
            "test_main.py": "from main import add\\ndef test_add():\\n    assert add(1, 2) == 3\\n",
        })
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="eval-repo-"))

    for filepath, content in files.items():
        full_path = tmpdir / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

    subprocess.run(
        ["git", "init"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "eval@posthog.com"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "PostHog Eval"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "add", "-A"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", commit_message],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )

    return tmpdir


def bugfix_repo() -> Path:
    """Sample repo with a bug for the agent to fix.

    The repo has a ``calculator.py`` with a broken ``divide`` function
    (returns multiplication instead of division) and a test that fails.
    """
    return create_temp_repo(
        {
            "calculator.py": (
                "def add(a: float, b: float) -> float:\n"
                "    return a + b\n"
                "\n"
                "\n"
                "def subtract(a: float, b: float) -> float:\n"
                "    return a - b\n"
                "\n"
                "\n"
                "def multiply(a: float, b: float) -> float:\n"
                "    return a * b\n"
                "\n"
                "\n"
                "def divide(a: float, b: float) -> float:\n"
                "    if b == 0:\n"
                "        raise ValueError('Cannot divide by zero')\n"
                "    return a * b  # BUG: should be a / b\n"
            ),
            "test_calculator.py": (
                "from calculator import add, subtract, multiply, divide\n"
                "import pytest\n"
                "\n"
                "\n"
                "def test_add():\n"
                "    assert add(2, 3) == 5\n"
                "\n"
                "\n"
                "def test_subtract():\n"
                "    assert subtract(5, 3) == 2\n"
                "\n"
                "\n"
                "def test_multiply():\n"
                "    assert multiply(4, 3) == 12\n"
                "\n"
                "\n"
                "def test_divide():\n"
                "    assert divide(10, 2) == 5\n"
                "\n"
                "\n"
                "def test_divide_by_zero():\n"
                "    with pytest.raises(ValueError):\n"
                "        divide(10, 0)\n"
            ),
        }
    )


def feature_repo() -> Path:
    """Sample repo where the agent should add a new feature.

    The repo has a ``string_utils.py`` with basic string utilities but is
    missing a ``reverse_words`` function. The test for it exists but is skipped.
    """
    return create_temp_repo(
        {
            "string_utils.py": (
                "def capitalize_words(text: str) -> str:\n"
                "    return ' '.join(word.capitalize() for word in text.split())\n"
                "\n"
                "\n"
                "def count_vowels(text: str) -> int:\n"
                "    return sum(1 for char in text.lower() if char in 'aeiou')\n"
            ),
            "test_string_utils.py": (
                "import pytest\n"
                "from string_utils import capitalize_words, count_vowels\n"
                "\n"
                "\n"
                "def test_capitalize_words():\n"
                "    assert capitalize_words('hello world') == 'Hello World'\n"
                "\n"
                "\n"
                "def test_count_vowels():\n"
                "    assert count_vowels('hello') == 2\n"
                "\n"
                "\n"
                "@pytest.mark.skip(reason='reverse_words not implemented yet')\n"
                "def test_reverse_words():\n"
                "    from string_utils import reverse_words\n"
                "    assert reverse_words('hello world') == 'world hello'\n"
                "    assert reverse_words('one') == 'one'\n"
                "    assert reverse_words('') == ''\n"
            ),
        }
    )
