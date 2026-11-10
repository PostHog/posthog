import os
import sys
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest


class TestCompileCorpus(unittest.TestCase):
    def test_compiler_failure_stops_the_corpus(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            valid = directory / "valid.hog"
            invalid = directory / "invalid.hog"
            valid.write_text("print(7);")
            invalid.write_text("let = ;")
            first = directory / "first.hoge"
            last = directory / "last.hoge"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.hogvm_compile",
                    str(valid),
                    str(first),
                    str(invalid),
                    str(directory / "invalid.hoge"),
                    str(valid),
                    str(last),
                ],
                cwd=Path(__file__).resolve().parents[4],
                env={
                    **os.environ,
                    "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
                    "TEST": "1",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(first.exists(), result.stdout + result.stderr)
            self.assertFalse(last.exists())
