import pytest
from posthog.test.base import BaseTest

from products.agent_memory.backend.facade import api


class TestAgentMemoryFacade(BaseTest):
    async def test_write_read_round_trip(self) -> None:
        written = await api.awrite_memory(
            team_id=self.team.id, path="project.md", content="hello", expected_version=None
        )
        assert written.version == 1
        assert written.content == "hello"

        read = await api.aread_memory(team_id=self.team.id, path="project.md")
        assert read.content == "hello"
        assert read.version == 1

    async def test_read_missing_raises(self) -> None:
        with pytest.raises(api.MemoryFileNotFoundError):
            await api.aread_memory(team_id=self.team.id, path="absent.md")

    async def test_cas_conflict_raises(self) -> None:
        await api.awrite_memory(team_id=self.team.id, path="p.md", content="v1", expected_version=None)
        with pytest.raises(api.MemoryVersionConflictError):
            await api.awrite_memory(team_id=self.team.id, path="p.md", content="dup", expected_version=None)

    async def test_append_section_returns_file(self) -> None:
        result = await api.aappend_section(team_id=self.team.id, path="project.md", heading="Notes", body="something")
        assert "## Notes" in result.content
        assert "something" in result.content

    async def test_list_returns_summaries(self) -> None:
        await api.awrite_memory(team_id=self.team.id, path="a.md", content="xx", expected_version=None)
        summaries = await api.alist_memory(team_id=self.team.id)
        assert len(summaries) == 1
        assert summaries[0].path == "a.md"
        assert summaries[0].size_bytes == 2

    async def test_delete(self) -> None:
        await api.awrite_memory(team_id=self.team.id, path="a.md", content="x", expected_version=None)
        assert await api.adelete_memory(team_id=self.team.id, path="a.md") is True
        assert await api.adelete_memory(team_id=self.team.id, path="a.md") is False
