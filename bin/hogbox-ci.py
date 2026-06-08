#!/usr/bin/env python3
"""Connectivity probe for the hogland-backed preview path.

v1 scope: prove a CI runner can authenticate to hogland's control plane
(hogplane) via GitHub Actions OIDC, over the tailnet, and drive a hogbox
end to end. This is the seed for a real per-PR preview environment (spin up
a box, deploy the stack, expose a proxy URL) -- see ci-hogbox-preview.yml.
Kept deliberately small so the first runs isolate the auth/reachability
question from everything else.

Env (set by the workflow):
  HOG_HOST   base URL of the target hogplane, e.g.
             https://hogland-dev.hedgehog-kitefin.ts.net (tailnet MagicDNS).
  HOG_TOKEN  a GitHub Actions OIDC JWT minted with audience
             hogland.<env>.posthog.dev. The SDK sends it as a bearer and
             hogplane's github_oidc verifier resolves it to a Principal.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

from hogland import Hogland


def _ephemeral_ssh_pubkey() -> str:
    """Generate a throwaway ed25519 keypair and return its public key line.

    TODO(keyless): drop this once hogland ships a keyless / api-only access
    mode for service kinds. A CI box only ever uses the HTTP exec/files/proxy
    API (never SSH), so the key here is dead weight that exists purely to
    satisfy the current cold-boot spec validation. Tracked in hogland.
    """
    with tempfile.TemporaryDirectory() as d:
        key = pathlib.Path(d) / "id_ed25519"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-C", "hogbox-ci-probe", "-f", str(key)],
            check=True,
        )
        return key.with_suffix(".pub").read_text().strip()


def main() -> int:
    client = Hogland()  # HOG_TOKEN + HOG_HOST from env
    print(f"[probe] host = {client.base_url}", flush=True)

    # 1) Auth + reachability: who does hogplane think we are?
    me = client.me()
    print(f"[probe] authenticated as: {me}", flush=True)

    # 2) A real authorized read against the API.
    limits = client.limits()
    print(f"[probe] limits: {limits}", flush=True)

    # 3) Full path: create a throwaway box, run a command, tear it down.
    #    kind="ci" (2h default TTL); the explicit ttl is the real backstop so
    #    the box self-reaps even if the context-manager cleanup is skipped.
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    with client.create(
        name=f"ci-probe-{run_id}",
        kind="ci",
        ttl_seconds=600,
        ssh_public_key=_ephemeral_ssh_pubkey(),  # TODO(keyless): remove
    ) as box:
        print(f"[probe] created box: {box.id} ({box.status})", flush=True)
        result = box.exec(["uname", "-a"], timeout_seconds=30)
        print(f"[probe] exec exit={result.exit_code} stdout={result.stdout!r}", flush=True)
        if result.exit_code != 0:
            print(f"[probe] exec stderr={result.stderr!r}", flush=True)
            return 1
    print("[probe] box destroyed (context exit)", flush=True)

    print("[probe] OK -- CI can reach + authenticate + drive hogland", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
