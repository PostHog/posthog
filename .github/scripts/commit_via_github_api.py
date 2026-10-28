#!/usr/bin/env python3
"""Commit files to a branch with GitHub's createCommitOnBranch mutation, so GitHub signs the commit.

The commit applies only on top of --expected-head. Safe to re-run: when an earlier run's commit
landed but GitHub's response was lost, the branch head is that commit, and the script exits 0
instead of failing on the moved head.

Standard library only. Needs the `gh` CLI and GH_TOKEN.
"""

import sys
import json
import base64
import argparse
import subprocess
from pathlib import Path
from typing import Any

GITHUB_TIMEOUT_SECONDS = 60

BRANCH_HEAD_QUERY = """
query($owner: String!, $name: String!, $ref: String!) {
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: $ref) {
      target { ... on Commit { oid messageHeadline parents(first: 2) { nodes { oid } } } }
    }
  }
}
"""

CREATE_COMMIT_MUTATION = """
mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { url } }
}
"""


def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=json.dumps({"query": query, "variables": variables}),
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        timeout=GITHUB_TIMEOUT_SECONDS,
    )
    return json.loads(result.stdout)["data"]


def file_changes(paths: list[str]) -> dict[str, list[dict[str, str]]]:
    changes: dict[str, list[dict[str, str]]] = {"additions": [], "deletions": []}
    for path in map(Path, paths):
        if path.exists():
            changes["additions"].append({"path": str(path), "contents": base64.b64encode(path.read_bytes()).decode()})
        else:
            changes["deletions"].append({"path": str(path)})
    return changes


def commit(repo: str, branch: str, expected_head: str, message: str, paths: list[str]) -> int:
    owner, name = repo.split("/")
    data = graphql(BRANCH_HEAD_QUERY, {"owner": owner, "name": name, "ref": f"refs/heads/{branch}"})
    head = data["repository"]["ref"]["target"]
    if head["oid"] != expected_head:
        parents = [parent["oid"] for parent in head["parents"]["nodes"]]
        if parents == [expected_head] and head["messageHeadline"] == message:
            sys.stdout.write(f"{branch} already has this commit: {head['oid']}\n")
            return 0
        sys.stdout.write(
            f"::error::{branch} moved from {expected_head} to {head['oid']}, so the commit was not made.\n"
        )
        return 1

    created = graphql(
        CREATE_COMMIT_MUTATION,
        {
            "input": {
                "branch": {"repositoryNameWithOwner": repo, "branchName": branch},
                "message": {"headline": message},
                "fileChanges": file_changes(paths),
                "expectedHeadOid": expected_head,
            }
        },
    )
    sys.stdout.write(f"New commit: {created['createCommitOnBranch']['commit']['url']}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--expected-head", required=True, help="the commit the new commit goes on top of")
    parser.add_argument("--message", required=True)
    parser.add_argument("paths", nargs="+", help="files to commit; a missing file is committed as a deletion")
    args = parser.parse_args()
    return commit(args.repo, args.branch, args.expected_head, args.message, args.paths)


if __name__ == "__main__":
    sys.exit(main())
