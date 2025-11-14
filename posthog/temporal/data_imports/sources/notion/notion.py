from collections.abc import Iterator
from typing import Any

import structlog

from posthog.temporal.data_imports.sources.notion.helpers import NotionClient

logger = structlog.get_logger(__name__)


def fetch_users(client: NotionClient) -> Iterator[dict[str, Any]]:
    """Fetch all users from Notion workspace."""
    yield from client.paginate_endpoint(client.list_users)


def fetch_pages(client: NotionClient, last_edited_time: str | None = None) -> Iterator[dict[str, Any]]:
    """Fetch all pages from Notion workspace."""
    # Search for all pages
    for page in client.paginate_endpoint(client.search, filter_type="page"):
        # Apply incremental filtering if last_edited_time is provided
        if last_edited_time:
            page_last_edited = page.get("last_edited_time", "")
            if page_last_edited <= last_edited_time:
                continue
        yield page


def fetch_databases(client: NotionClient, last_edited_time: str | None = None) -> Iterator[dict[str, Any]]:
    """Fetch all databases from Notion workspace."""
    # Search for all databases
    for database in client.paginate_endpoint(client.search, filter_type="database"):
        # Apply incremental filtering if last_edited_time is provided
        if last_edited_time:
            db_last_edited = database.get("last_edited_time", "")
            if db_last_edited <= last_edited_time:
                continue
        yield database


def fetch_blocks(client: NotionClient, last_edited_time: str | None = None) -> Iterator[dict[str, Any]]:
    """Fetch all blocks from all pages in the workspace."""
    # First, get all pages
    for page in client.paginate_endpoint(client.search, filter_type="page"):
        page_id = page.get("id")
        if not page_id:
            continue

        # Get all blocks from this page
        try:
            for block in client.paginate_endpoint(client.get_block_children, page_id):
                # Apply incremental filtering if last_edited_time is provided
                if last_edited_time:
                    block_last_edited = block.get("last_edited_time", "")
                    if block_last_edited <= last_edited_time:
                        continue

                # Add page_id to block for context
                block["page_id"] = page_id
                yield block

                # If block has children, recursively fetch them
                if block.get("has_children"):
                    block_id = block.get("id")
                    if block_id:
                        try:
                            for child_block in client.paginate_endpoint(client.get_block_children, block_id):
                                if last_edited_time:
                                    child_last_edited = child_block.get("last_edited_time", "")
                                    if child_last_edited <= last_edited_time:
                                        continue
                                child_block["page_id"] = page_id
                                child_block["parent_block_id"] = block_id
                                yield child_block
                        except Exception as e:
                            logger.warning(f"Failed to fetch children for block {block_id}: {e}")
        except Exception as e:
            logger.warning(f"Failed to fetch blocks for page {page_id}: {e}")


def fetch_comments(client: NotionClient, created_time: str | None = None) -> Iterator[dict[str, Any]]:
    """Fetch all comments from all pages in the workspace."""
    # First, get all pages
    for page in client.paginate_endpoint(client.search, filter_type="page"):
        page_id = page.get("id")
        if not page_id:
            continue

        # Get all comments for this page
        try:
            for comment in client.paginate_endpoint(client.get_comments, page_id):
                # Apply incremental filtering if created_time is provided
                if created_time:
                    comment_created = comment.get("created_time", "")
                    if comment_created <= created_time:
                        continue

                # Add page_id to comment for context
                comment["page_id"] = page_id
                yield comment
        except Exception as e:
            logger.warning(f"Failed to fetch comments for page {page_id}: {e}")


def notion_source(
    access_token: str,
    endpoint: str,
    last_edited_time: str | None = None,
    created_time: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """
    Main source function for fetching data from Notion.

    Args:
        access_token: Notion OAuth access token
        endpoint: The endpoint to fetch data from (users, pages, databases, blocks, comments)
        last_edited_time: For incremental syncs on endpoints that use last_edited_time
        created_time: For incremental syncs on endpoints that use created_time (comments)
    """
    client = NotionClient(access_token)

    batch: list[dict[str, Any]] = []
    batch_size = 100

    if endpoint == "users":
        items = fetch_users(client)
    elif endpoint == "pages":
        items = fetch_pages(client, last_edited_time)
    elif endpoint == "databases":
        items = fetch_databases(client, last_edited_time)
    elif endpoint == "blocks":
        items = fetch_blocks(client, last_edited_time)
    elif endpoint == "comments":
        items = fetch_comments(client, created_time)
    else:
        raise ValueError(f"Unknown endpoint: {endpoint}")

    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []

    # Yield any remaining items
    if batch:
        yield batch
