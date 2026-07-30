#!/usr/bin/env python3
# ruff: noqa: T201 — standalone CLI payload, print is the output channel
"""Recreate a dashboard (from a `dashboard-get` JSON dump) in a PostHog instance.

TEMPORARY preview-seed payload for the PR #74534 / #74545 comparison — a copy
of the local tmp/recreate_dashboard_locally.py with preview extras: --replace
(drop same-name dashboards first), --clear-test-filters, and --refresh
(force-recompute every tile so the dashboard opens warm).

Usage (inside the box's web image):
    python recreate_dashboard.py dashboard-fixture.json --api-key phx_... \
        [--host http://web:8000] [--project-id @current] [--replace] \
        [--clear-test-filters] [--refresh]
"""

import os
import sys
import json
import argparse

import requests


def strip_layout(layouts: dict) -> dict:
    # `i` is the source tile id; the local grid assigns its own.
    return {bp: {k: v for k, v in (geom or {}).items() if k != "i"} for bp, geom in (layouts or {}).items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture")
    ap.add_argument("--host", default=os.environ.get("POSTHOG_URL", "http://localhost:8000"))
    ap.add_argument("--api-key", default=os.environ.get("POSTHOG_API_KEY"))
    ap.add_argument("--project-id", default="@current", help="Project id the dashboard goes into")
    ap.add_argument("--replace", action="store_true", help="Soft-delete same-name dashboards first")
    ap.add_argument("--clear-test-filters", action="store_true", help="Clear the team's test_account_filters")
    ap.add_argument("--refresh", action="store_true", help="Force-refresh every created insight at the end")
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("Pass --api-key or set POSTHOG_API_KEY")

    with open(args.fixture) as f:
        source = json.load(f)

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {args.api_key}"
    base = f"{args.host}/api/projects/{args.project_id}"

    if args.clear_test_filters:
        r = session.patch(f"{base}/", json={"test_account_filters": []})
        print(f"cleared test_account_filters: {r.status_code}")

    if args.replace:
        r = session.get(f"{base}/dashboards/", params={"search": source["name"], "limit": 100})
        for dash in r.json().get("results", []):
            if dash["name"] == source["name"]:
                session.patch(f"{base}/dashboards/{dash['id']}/", json={"deleted": True})
                print(f"soft-deleted existing dashboard {dash['id']}")

    resp = session.post(
        f"{base}/dashboards/",
        json={"name": source["name"], "description": source.get("description") or ""},
    )
    resp.raise_for_status()
    dashboard_id = resp.json()["id"]
    print(f"created dashboard {dashboard_id}: {source['name']}")

    def tile_y(tile: dict) -> tuple:
        geom = (tile.get("layouts") or {}).get("sm") or {}
        return (geom.get("y") or 0, geom.get("x") or 0)

    tiles = sorted(source["tiles"], key=tile_y)

    # source tile id -> how to find the created tile later (insight id or text body)
    created_insights: dict[int, int] = {}
    text_bodies: dict[int, str] = {}

    for tile in tiles:
        if tile.get("insight"):
            ins = tile["insight"]
            payload = {
                "name": ins.get("name") or ins.get("derived_name") or "",
                "description": ins.get("description") or "",
                "query": ins["query"],
                "saved": True,
                "dashboards": [dashboard_id],
            }
            r = session.post(f"{base}/insights/", json=payload)
            if r.status_code >= 400:
                print(f"  FAILED insight {payload['name']!r}: {r.status_code} {r.text[:300]}")
                continue
            created_insights[tile["id"]] = r.json()["id"]
            print(f"  insight: {payload['name']}")
        elif tile.get("text"):
            body = tile["text"]["body"]
            r = session.patch(
                f"{base}/dashboards/{dashboard_id}/",
                json={
                    "tiles": [
                        {
                            "text": {"body": body},
                            "layouts": strip_layout(tile.get("layouts")),
                            "color": tile.get("color"),
                        }
                    ]
                },
            )
            if r.status_code >= 400:
                print(f"  FAILED text tile: {r.status_code} {r.text[:300]}")
                continue
            text_bodies[tile["id"]] = body
            print(f"  text tile: {body[:60]!r}")

    # Second pass: copy layouts onto the created tiles.
    r = session.get(f"{base}/dashboards/{dashboard_id}/")
    r.raise_for_status()
    local_tiles = r.json()["tiles"]
    by_insight = {t["insight"]["id"]: t["id"] for t in local_tiles if t.get("insight")}
    by_body = {t["text"]["body"]: t["id"] for t in local_tiles if t.get("text")}

    layout_updates = []
    for tile in tiles:
        local_tile_id = None
        if tile["id"] in created_insights:
            local_tile_id = by_insight.get(created_insights[tile["id"]])
        elif tile["id"] in text_bodies:
            local_tile_id = by_body.get(text_bodies[tile["id"]])
        if local_tile_id and tile.get("layouts"):
            layout_updates.append({"id": local_tile_id, "layouts": strip_layout(tile["layouts"])})

    if layout_updates:
        r = session.patch(f"{base}/dashboards/{dashboard_id}/", json={"tiles": layout_updates})
        if r.status_code >= 400:
            print(f"layout pass failed (dashboard still usable): {r.status_code} {r.text[:300]}")
        else:
            print(f"copied layouts for {len(layout_updates)} tiles")

    if args.refresh:
        # force_blocking bypasses any cached result — freshly inserted events
        # would otherwise hide behind a still-fresh cache entry.
        print(f"refreshing {len(created_insights)} insights (blocking)")
        for n, insight_id in enumerate(created_insights.values(), 1):
            try:
                r = session.get(
                    f"{base}/insights/{insight_id}/",
                    params={"refresh": "force_blocking"},
                    timeout=180,
                )
                print(f"  [{n}/{len(created_insights)}] insight {insight_id}: {r.status_code}")
            except requests.RequestException as e:
                print(f"  [{n}/{len(created_insights)}] insight {insight_id}: {type(e).__name__} (non-fatal)")

    print(f"\ndone: dashboard {dashboard_id} ({source['name']})")


if __name__ == "__main__":
    main()
