from unittest.mock import Mock


def mock_sentry_context_for_tagging(patched_scope):
    mock_scope = Mock()
    mock_set_tag = Mock()
    mock_scope.set_context = Mock()
    mock_scope.set_tag = mock_set_tag
    mock_context_manager = Mock()
    mock_context_manager.__enter__ = Mock(return_value=mock_scope)
    mock_context_manager.__exit__ = Mock(return_value=None)
    patched_scope.return_value = mock_context_manager
    return mock_set_tag
