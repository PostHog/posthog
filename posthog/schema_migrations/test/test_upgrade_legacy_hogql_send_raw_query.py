from posthog.schema_migrations.upgrade import upgrade


def test_upgrade_renames_skip_direct_hogql_to_send_raw_query():
    query = {"kind": "HogQLQuery", "query": "SELECT 1", "skipDirectHogQL": True}

    got = upgrade(query)

    assert got == {"kind": "HogQLQuery", "query": "SELECT 1", "sendRawQuery": True}


def test_upgrade_renames_run_directly_to_send_raw_query():
    query = {"kind": "HogQLQuery", "query": "SELECT 1", "runDirectly": True}

    got = upgrade(query)

    assert got == {"kind": "HogQLQuery", "query": "SELECT 1", "sendRawQuery": True}


def test_upgrade_preserves_existing_send_raw_query():
    query = {
        "kind": "HogQLQuery",
        "query": "SELECT 1",
        "skipDirectHogQL": True,
        "runDirectly": True,
        "sendRawQuery": False,
    }

    got = upgrade(query)

    assert got == {"kind": "HogQLQuery", "query": "SELECT 1", "sendRawQuery": False}
