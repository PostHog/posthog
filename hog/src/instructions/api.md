# Calling the PostHog API

`hog api` runs the tools PostHog's MCP server offers, with your hog login.
For PostHog tasks, read the matching skill first with `hog skills search <keywords>`. Skills name the tools to use.

1. Find a tool with `hog api search <words>`, or list groups with `hog api groups` and their tools with `hog api tools <group>`.
2. Run `hog api info <tool>` to see what the tool does, the scopes it needs, and whether it is destructive.
3. Run `hog api schema <tool>` for its input schema. Add a dotted path, such as `filters.groups`, to see one nested field.
4. Check the input with `hog api call <tool> '<json>' --dry-run`. It validates the input and calls nothing.
5. Call it with `hog api call <tool> '<json>'`. Pass `-` instead of the JSON to read it from stdin.

- A destructive tool needs `--confirm`. Ask the person before you pass it.
- `--project-id` calls a tool in another project, and `--organization-id` names the organization for organization-level tools.
- `hog api call` checks your scopes before it calls a tool. A missing scope fails with `step_up_required`. See `hog instructions auth`.
- `hog api access` shows which missing scopes block the most tools.
- hog updates the tool list from PostHog once a day. When an error says the tool definitions may be out of date, run `hog api refresh`.
