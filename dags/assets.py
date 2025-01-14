import json
import requests

import pandas as pd

from posthog.temporal.common.clickhouse import get_client

from dagster import (
    Config,
    MaterializeResult,
    MetadataValue,
    asset,
)

from asgiref.sync import async_to_sync


@asset
def get_clickhouse_version() -> MaterializeResult:
    @async_to_sync
    async def _get_version():
        async with get_client() as connection:
            version = await connection.apost_query("SELECT version()", query_id="version", query_parameters={})
            return version[0][0]

    version = _get_version()
    return MaterializeResult(version)


class HNStoriesConfig(Config):
    top_stories_limit: int = 10
    hn_top_story_ids_path: str = "hackernews_top_story_ids.json"
    hn_top_stories_path: str = "hackernews_top_stories.csv"


@asset
def hackernews_top_story_ids(config: HNStoriesConfig):
    """Get top stories from the HackerNews top stories endpoint."""
    top_story_ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json").json()

    with open(config.hn_top_story_ids_path, "w") as f:
        json.dump(top_story_ids[: config.top_stories_limit], f)


@asset(deps=[hackernews_top_story_ids])
def hackernews_top_stories(config: HNStoriesConfig) -> MaterializeResult:
    """Get items based on story ids from the HackerNews items endpoint."""
    with open(config.hn_top_story_ids_path) as f:
        hackernews_top_story_ids = json.load(f)

    results = []
    for item_id in hackernews_top_story_ids:
        item = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json").json()
        results.append(item)

    df = pd.DataFrame(results)
    df.to_csv(config.hn_top_stories_path)

    return MaterializeResult(
        metadata={
            "num_records": len(df),
            "preview": MetadataValue.md(str(df[["title", "by", "url"]].to_markdown())),
        }
    )
