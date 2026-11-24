FIELD_EXCLUSIONS = {
    # Tiles are edited through their own endpoint, so diffing the reverse relation only reads every tile row.
    "CrossProjectDashboard": ["tiles", "organization"],
}
