# JSONCleanPostHogEventNestedAsStrings fixtures

Two TabSeparated columns per row: the raw event properties and the raw person properties. The reference holds the named tuple ClickHouse prints for each row. Every top-level object and array, except the event `$feature_flags` map, comes back as a string of the text that was sent.
