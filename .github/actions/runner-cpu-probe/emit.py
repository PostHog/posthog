"""Serialize the probe readings as one JSON line for log scraping."""

import os
import json

FIELDS = {
    "runner_name": "RUNNER_NAME",
    "cpu_model": "RUNNER_MODEL",
    "cpu_vendor": "RUNNER_VENDOR",
    "cpu_family": "RUNNER_FAMILY",
    "cpu_stepping": "RUNNER_STEPPING",
    "hypervisor": "RUNNER_HYPERVISOR",
    "cpu_max_mhz": "RUNNER_MHZ",
    "bogomips": "RUNNER_BOGOMIPS",
    "cores": "RUNNER_CORES",
    "mem_gb": "RUNNER_MEM_GB",
    "sha256_1t_kbps": "SHA256_1T",
    "sha256_nt_kbps": "SHA256_NT",
    "dd_write": "DD_WRITE",
    "small_files_secs": "SMALL_SECS",
    "run_id": "GITHUB_RUN_ID",
    "attempt": "GITHUB_RUN_ATTEMPT",
    "job": "GITHUB_JOB",
}

print(json.dumps({key: os.environ.get(source, "") for key, source in FIELDS.items()}))
