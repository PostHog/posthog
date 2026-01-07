from typing import Any

from posthog.test.base import BaseTest

from ee.hogai.tools.todo_write import TodoItem, TodoWriteTool
import pytest


class TestTodoWriteTool(BaseTest):
    def test_format_todo_list_empty_list(self):
        """Test formatting an empty todo list from list"""
        result = TodoWriteTool.format_todo_list([])
        assert result == "Your todo list is empty."

    def test_format_todo_list_empty_args(self):
        """Test formatting an empty todo list from args dict"""
        args: dict[str, Any] = {"todos": []}
        result = TodoWriteTool.format_todo_list(args)
        assert result == "Your todo list is empty."

    def test_format_todo_list_missing_todos_key(self):
        """Test formatting from args with missing todos key raises validation error"""
        from pydantic import ValidationError

        args: dict[str, Any] = {}
        with pytest.raises(ValidationError):
            TodoWriteTool.format_todo_list(args)

    def test_format_todo_list_single_pending_from_objects(self):
        """Test formatting a single pending todo from TodoItem objects"""
        todos = [TodoItem(content="Task 1", status="pending", id="1")]
        result = TodoWriteTool.format_todo_list(todos)
        expected = "Your current todo list:\n○ [pending] Task 1"
        assert result == expected

    def test_format_todo_list_single_pending_from_args(self):
        """Test formatting a single pending todo from args dict"""
        args = {"todos": [{"content": "Task 1", "status": "pending", "id": "1"}]}
        result = TodoWriteTool.format_todo_list(args)
        expected = "Your current todo list:\n○ [pending] Task 1"
        assert result == expected

    def test_format_todo_list_single_in_progress(self):
        """Test formatting a single in-progress todo"""
        todos = [TodoItem(content="Task 2", status="in_progress", id="2")]
        result = TodoWriteTool.format_todo_list(todos)
        expected = "Your current todo list:\n→ [in_progress] Task 2"
        assert result == expected

    def test_format_todo_list_single_completed(self):
        """Test formatting a single completed todo"""
        todos = [TodoItem(content="Task 3", status="completed", id="3")]
        result = TodoWriteTool.format_todo_list(todos)
        expected = "Your current todo list:\n✓ [completed] Task 3"
        assert result == expected

    def test_format_todo_list_multiple_statuses_from_objects(self):
        """Test formatting a list with multiple different statuses from objects"""
        todos = [
            TodoItem(content="Pending task", status="pending", id="1"),
            TodoItem(content="In progress task", status="in_progress", id="2"),
            TodoItem(content="Completed task", status="completed", id="3"),
        ]
        result = TodoWriteTool.format_todo_list(todos)
        expected = (
            "Your current todo list:\n"
            "○ [pending] Pending task\n"
            "→ [in_progress] In progress task\n"
            "✓ [completed] Completed task"
        )
        assert result == expected

    def test_format_todo_list_multiple_statuses_from_args(self):
        """Test formatting a list with multiple different statuses from args dict"""
        args = {
            "todos": [
                {"content": "Find events", "status": "pending", "id": "1"},
                {"content": "Create plan", "status": "in_progress", "id": "2"},
                {"content": "Analyze data", "status": "completed", "id": "3"},
            ]
        }
        result = TodoWriteTool.format_todo_list(args)

        # Check all status indicators are present
        assert "○ [pending] Find events" in result
        assert "→ [in_progress] Create plan" in result
        assert "✓ [completed] Analyze data" in result
        assert "Your current todo list:" in result
