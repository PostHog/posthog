manifest_input_checksums() {
    jq -r --arg prefix "$2" '
        (.inputs // {}) | to_entries[] | select(.key | startswith($prefix)) |
        if (.key | test("^[A-Za-z0-9_-][A-Za-z0-9_.-]*(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*\\z")) and
           (.value | type == "string" and test("^[0-9a-f]{64}\\z"))
        then "\(.value)  \(.key)" else error("Invalid input manifest entry") end
    ' "$1/manifest.json"
}
