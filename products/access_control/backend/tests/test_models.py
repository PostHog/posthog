from products.access_control.backend.models.access_control import AccessControl


def test_access_control_keeps_existing_database_table() -> None:
    assert AccessControl._meta.db_table == "ee_accesscontrol"
