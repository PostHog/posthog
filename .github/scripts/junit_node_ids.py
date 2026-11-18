#!/usr/bin/env python3
"""Map pytest JUnit XML testcases back to pytest node ids.

`failed` prints the node id of every testcase with a <failure> or <error>.
`missing` prints each expected node id that no testcase in the reports ran, and exits 1 if there is one.

pytest writes a testcase as classname "path.to.test_module.Class" and name "test[param]".
The dotted classname loses the boundary between the module path and the class names, so the
module is the longest dotted prefix that names a .py file under the rootdir.
"""

from __future__ import annotations

import sys
import argparse
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree


class UnresolvableTestcase(Exception):
    pass


@dataclass(frozen=True, kw_only=True, slots=True)
class Testcase:
    node_id: str
    failed: bool


def _module_path(dotted: list[str], rootdir: Path) -> str | None:
    relative = "/".join(dotted)
    if (rootdir / f"{relative}.py").is_file():
        return f"{relative}.py"
    return None


def node_id(classname: str, name: str, rootdir: Path) -> str:
    # A collection error has no classname, and its name is the dotted path of the module or directory.
    if not classname:
        dotted = name.split(".")
        module = _module_path(dotted, rootdir)
        if module is not None:
            return module
        if (rootdir / "/".join(dotted)).is_dir():
            return "/".join(dotted)
        raise UnresolvableTestcase(f"no module or directory under {rootdir} matches collection error {name!r}")

    parts = classname.split(".")
    for split in range(len(parts), 0, -1):
        module = _module_path(parts[:split], rootdir)
        if module is not None:
            return "::".join([module, *parts[split:], name])
    raise UnresolvableTestcase(f"no module under {rootdir} matches testcase {classname!r} {name!r}")


def _testcases(reports: Iterable[Path], rootdir: Path) -> Iterator[Testcase]:
    for report in reports:
        for testcase in ElementTree.parse(report).getroot().iter("testcase"):
            yield Testcase(
                node_id=node_id(testcase.get("classname", ""), testcase.get("name", ""), rootdir),
                failed=testcase.find("failure") is not None or testcase.find("error") is not None,
            )


def failed_node_ids(reports: Iterable[Path], rootdir: Path) -> list[str]:
    return list(dict.fromkeys(testcase.node_id for testcase in _testcases(reports, rootdir) if testcase.failed))


def missing_node_ids(expected: Iterable[str], reports: Iterable[Path], rootdir: Path) -> list[str]:
    ran = {testcase.node_id for testcase in _testcases(reports, rootdir)}
    # A module id comes from a collection error. Any test that ran from that module shows it collected.
    return [
        expected_id
        for expected_id in expected
        if expected_id not in ran and not any(ran_id.startswith(f"{expected_id}::") for ran_id in ran)
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rootdir", type=Path, default=Path.cwd(), help="pytest rootdir the node ids are relative to")
    subcommands = parser.add_subparsers(dest="command", required=True)
    failed = subcommands.add_parser("failed")
    failed.add_argument("reports", nargs="+", type=Path)
    missing = subcommands.add_parser("missing")
    missing.add_argument("--expected", type=Path, required=True, help="file with one expected node id per line")
    missing.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "failed":
            ids = failed_node_ids(args.reports, args.rootdir)
        else:
            expected = [line for line in args.expected.read_text().splitlines() if line]
            ids = missing_node_ids(expected, args.reports, args.rootdir)
    except (OSError, ElementTree.ParseError, UnresolvableTestcase) as error:
        sys.stderr.write(f"::error::{error}\n")
        return 2

    sys.stdout.writelines(f"{found}\n" for found in ids)
    return 1 if args.command == "missing" and ids else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
