from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.notebooks.backend.models import Notebook

from ee.hogai.tools.create_notebook.tiptap import tiptap_doc_to_text

from .prompts import NOTEBOOK_CONTEXT_TEMPLATE


class NotebookContext:
    def __init__(
        self,
        team: Team,
        short_id: str,
        title: str | None = None,
        content_doc: dict | None = None,
        text_content: str | None = None,
        created_at: str | None = None,
        last_modified_at: str | None = None,
    ):
        self._team = team
        self._short_id = short_id
        self._title = title
        self._content_doc = content_doc
        self._text_content = text_content
        self._created_at = created_at
        self._last_modified_at = last_modified_at

    @classmethod
    def from_model(cls, team: Team, notebook: Notebook) -> "NotebookContext":
        return cls(
            team=team,
            short_id=notebook.short_id,
            title=notebook.title,
            content_doc=notebook.content,
            text_content=notebook.text_content,
            created_at=notebook.created_at.isoformat() if notebook.created_at else None,
            last_modified_at=notebook.last_modified_at.isoformat() if notebook.last_modified_at else None,
        )

    @classmethod
    async def from_short_id(cls, team: Team, short_id: str) -> "NotebookContext | None":
        @database_sync_to_async(thread_sensitive=False)
        def _fetch():
            try:
                return Notebook.objects.get(short_id=short_id, team=team, deleted=False)
            except Notebook.DoesNotExist:
                return None

        notebook = await _fetch()
        if notebook is None:
            return None

        return cls.from_model(team, notebook)

    def format(self) -> str:
        content = tiptap_doc_to_text(self._content_doc)
        if not content and self._text_content:
            content = self._text_content
        if not content:
            content = "(empty notebook)"

        return NOTEBOOK_CONTEXT_TEMPLATE.format(
            title=self._title or "Untitled",
            short_id=self._short_id,
            created_at=self._created_at or "unknown",
            last_modified_at=self._last_modified_at or "unknown",
            url=f"/notebooks/{self._short_id}",
            content=content,
        )
