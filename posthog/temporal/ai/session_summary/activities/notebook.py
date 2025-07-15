from tkinter.ttk import Notebook
from elevenlabs import User

from posthog.caching.test.test_stale_utils import Team


def create_summary_notebook(session_ids: list[str], user: User, team: Team) -> Notebook:
    """Create a notebook with header and session IDs covered"""
    notebook_content = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "Summaries generated"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": f"Session ids covered: {', '.join(session_ids)}"}],
            },
        ],
    }

    notebook = Notebook.objects.create(
        team=team,
        title="Session Summaries",
        content=notebook_content,
        created_by=user,
        last_modified_by=user,
    )

    return notebook
