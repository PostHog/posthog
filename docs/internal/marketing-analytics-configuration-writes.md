# Marketing configuration writes

Settings updates send only the changed field and refresh the Marketing configuration under a row lock, preserving unrelated concurrent changes.

Explicit conversion-goal list updates still replace the list; simultaneous edits to that same list are not merged.

Loading a project replaces the current and saved Marketing settings with that project’s configuration, including an empty configuration when none exists.
