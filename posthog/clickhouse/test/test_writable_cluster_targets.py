import re
from pathlib import Path

from unittest import TestCase

# Cloud `<cluster>_writable` clusters list every online writable replica of a shard, so any of them can
# take a write. A non-replicated target keeps those rows on that one replica.
HCL_SQL_DIR = Path(__file__).resolve().parents[1] / "hcl" / "sql"
CREATE_TABLE_RE = re.compile(
    r"^CREATE TABLE (?:IF NOT EXISTS )?(\w+)\.(\w+) \(.*?^\) ENGINE = (\w+)\((.*?)\)", re.M | re.S
)
WRITABLE_CLUSTER_RE = re.compile(r"^'([\w-]+_writable)',\s*'(\w+)',\s*'(\w+)'")


def _tables(env_dir: Path) -> dict[tuple[str, str], tuple[str, str]]:
    tables: dict[tuple[str, str], tuple[str, str]] = {}
    for path in sorted(env_dir.glob("*.sql")):
        for database, name, engine, args in CREATE_TABLE_RE.findall(path.read_text()):
            tables[(database, name)] = (engine, args)
    return tables


class TestWritableClusterTargets(TestCase):
    def test_distributed_tables_on_writable_clusters_target_replicated_tables(self) -> None:
        env_dirs = sorted(path for path in HCL_SQL_DIR.iterdir() if path.is_dir())
        self.assertTrue(env_dirs, f"no generated HCL SQL under {HCL_SQL_DIR}")

        checked = 0
        failures = []
        for env_dir in env_dirs:
            tables = _tables(env_dir)
            for (database, name), (engine, args) in tables.items():
                if engine != "Distributed":
                    continue
                match = WRITABLE_CLUSTER_RE.match(args)
                if not match:
                    continue
                cluster, target_database, target_name = match.groups()
                target = tables.get((target_database, target_name))
                # A target this env doesn't declare is `hclexp validate`'s concern, not this test's.
                if target is None:
                    continue
                checked += 1
                if not target[0].startswith("Replicated"):
                    failures.append(
                        f"{env_dir.name}: {database}.{name} writes through {cluster} into "
                        f"{target_database}.{target_name}, which is {target[0]}"
                    )

        self.assertGreater(checked, 0, "found no Distributed tables on a *_writable cluster to check")
        self.assertEqual(failures, [], "Distributed tables on *_writable clusters must target Replicated* tables")
