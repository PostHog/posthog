def pretty_print_in_tests(query: str, team_id: int) -> str:
    return (
        query.replace("SELECT", "\nSELECT")
        .replace("FROM", "\nFROM")
        .replace("WHERE", "\nWHERE")
        .replace("GROUP", "\nGROUP")
        .replace("HAVING", "\nHAVING")
        .replace("LIMIT", "\nLIMIT")
        .replace("SETTINGS", "\nSETTINGS")
        .replace(f"team_id, {team_id})", "team_id, 420)")
    )
