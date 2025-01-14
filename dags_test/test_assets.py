import os
import unittest

from dagster_quickstart.assets import HNStoriesConfig, hackernews_top_story_ids, hackernews_top_stories
from unittest import mock


CONFIG = HNStoriesConfig(
    hn_top_story_ids_path="dagster_quickstart_tests/hackernews_top_story_ids.json",
    hn_top_stories_path="dagster_quickstart_tests/hackernews_top_stories.csv",
)


@mock.patch("builtins.open")
@mock.patch("requests.get")
def test_hackernews_top_story_ids(mock_get, mock_open):
    mock_response = mock.Mock()
    mock_response.json.return_value = [1, 2, 3, 4, 5]
    mock_get.return_value = mock_response

    hackernews_top_story_ids(CONFIG)

    mock_get.assert_called_with("https://hacker-news.firebaseio.com/v0/topstories.json")
    mock_open.assert_called_with(CONFIG.hn_top_story_ids_path, "w")


@mock.patch("requests.get")
def test_hackernews_top_stories(mock_get):
    mock_response = mock.Mock()
    mock_response.json.return_value = {
        "title": "Mock Title",
        "by": "John Smith",
        "url": "www.example.com",
    }
    mock_get.return_value = mock_response

    materialized_results = hackernews_top_stories(CONFIG)
    assert materialized_results.metadata.get("num_records") == 10
    os.remove("dagster_quickstart_tests/hackernews_top_stories.csv")


if __name__ == "__main__":
    unittest.main()
