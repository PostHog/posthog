import time
import uuid
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from posthog.hogql_queries import replay


class Command(BaseCommand):
    help = "Replay logged queries against two versions of the code and report result and cost changes"

    def add_arguments(self, parser: ArgumentParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True)

        sample = actions.add_parser("sample", help="Select logged queries by ID, or sample recent ones")
        sample.add_argument("--out", type=Path, required=True)
        sample.add_argument("--query-id", action="append", default=[])
        sample.add_argument("--sample", type=int, default=0)

        compile_ = actions.add_parser("compile", help="Compile selected queries to SQL without running them")
        compile_.add_argument("--sample-file", type=Path, required=True)
        compile_.add_argument("--out", type=Path, required=True)

        run = actions.add_parser("run", help="Run queries whose SQL changed and write the report")
        run.add_argument("--sample-file", type=Path, required=True)
        run.add_argument("--base", type=Path, required=True)
        run.add_argument("--head", type=Path, required=True)
        run.add_argument("--out-dir", type=Path, required=True)
        run.add_argument("--base-label", default="")
        run.add_argument("--head-label", default="")
        run.add_argument("--max-executed", type=int, default=replay.MAX_EXECUTED)
        run.add_argument("--query-log-wait-seconds", type=int, default=15)

        upload = actions.add_parser("upload", help="Copy a file or folder to object storage")
        upload.add_argument("--path", type=Path, required=True)
        upload.add_argument("--key", required=True)

        download = actions.add_parser("download", help="Copy one object from object storage to a file")
        download.add_argument("--key", required=True)
        download.add_argument("--path", type=Path, required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        getattr(self, f"_{options['action']}")(options)

    def _sample(self, options: dict[str, Any]) -> None:
        if not options["query_id"] and not options["sample"]:
            self.stderr.write("Pass --query-id or --sample")
            raise SystemExit(2)
        logged = replay.load_logged_queries(options["query_id"], options["sample"])
        replay.write_jsonl(options["out"], logged)
        self.stdout.write(f"Selected {len(logged)} queries")

    def _compile(self, options: dict[str, Any]) -> None:
        logged = replay.read_logged_queries(options["sample_file"])
        replay.write_jsonl(options["out"], (replay.compile_logged_query(query) for query in logged))
        self.stdout.write(f"Compiled {len(logged)} queries")

    def _run(self, options: dict[str, Any]) -> None:
        run_id = uuid.uuid4().hex
        outcomes = replay.run_replay(
            replay.read_logged_queries(options["sample_file"]),
            replay.read_compiled_queries(options["base"]),
            replay.read_compiled_queries(options["head"]),
            run_id=run_id,
            max_executed=options["max_executed"],
        )
        time.sleep(options["query_log_wait_seconds"])
        summary = replay.summarize(
            outcomes, replay.load_read_bytes(run_id), options["base_label"], options["head_label"]
        )
        replay.write_report(summary, outcomes, options["out_dir"])
        self.stdout.write(f"{summary['counts']} regressions={summary['regressions']}")

    def _upload(self, options: dict[str, Any]) -> None:
        replay.upload(options["path"], options["key"])

    def _download(self, options: dict[str, Any]) -> None:
        replay.download(options["key"], options["path"])
