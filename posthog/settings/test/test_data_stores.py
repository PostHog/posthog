from parameterized import parameterized

from posthog.settings.data_stores import (
    _add_default_transaction_read_only_option,
    _is_manage_py_shell_command,
    _should_enforce_read_only_for_exec,
)


@parameterized.expand(
    [
        ("django_shell", ["manage.py", "shell"], True),
        ("django_shell_plus", ["manage.py", "shell_plus"], True),
        ("django_dbshell", ["manage.py", "dbshell"], True),
        ("django_runserver", ["manage.py", "runserver"], False),
        ("not_enough_args", ["manage.py"], False),
    ]
)
def test_is_manage_py_shell_command(_: str, argv: list[str], expected: bool) -> None:
    assert _is_manage_py_shell_command(argv) is expected


@parameterized.expand(
    [
        ("k8s_shell_without_override", {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, ["manage.py", "shell"], True),
        (
            "k8s_shell_with_override",
            {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "ALLOW_POD_SHELL_DB_WRITE": "true"},
            ["manage.py", "shell"],
            False,
        ),
        ("k8s_runserver", {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, ["manage.py", "runserver"], False),
        ("not_k8s_shell", {}, ["manage.py", "shell"], False),
    ]
)
def test_should_enforce_read_only_for_exec(_: str, env: dict[str, str], argv: list[str], expected: bool) -> None:
    assert _should_enforce_read_only_for_exec(env, argv) is expected


def test_add_default_transaction_read_only_option() -> None:
    database_config: dict = {"OPTIONS": {"options": "-c statement_timeout=5000"}}

    _add_default_transaction_read_only_option(database_config)
    _add_default_transaction_read_only_option(database_config)

    assert database_config["OPTIONS"]["options"] == "-c statement_timeout=5000 -c default_transaction_read_only=on"
