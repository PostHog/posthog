# Space files

Space files are shared Markdown files that belong to one Space in PostHog Desktop.
They provide durable working notes, such as a project plan or `TODO.md`, across tasks.

## Use a file

1. Open **Files** in the navigation rail.
2. Select a file, or select **New file…** to create one in a Space.
3. Use the preview and source controls to read the file.
4. Select **Edit** to change the Markdown source.

A save replaces the complete file content and creates a new version number.
If another user or agent changed the file, PostHog keeps your draft and asks you to reload the latest content.

## Send selected text to an agent

Select text in the preview or source view, then select **Send to agent**.
PostHog opens a task draft in the file's Space.
The task tells the agent to read the current file before work and update it after work.

## Agent access

Agents can use these MCP tools when the Space files feature flag is enabled:

- `space-files-list`
- `space-files-get`
- `space-files-update`

A task agent can access files only in its assigned Space.
The update tool requires the current version number and rejects an update based on an old version.

## Limits

- Files must use a flat name that ends in `.md`.
- A Space cannot contain two files with the same name, including names that differ only by letter case.
- Each file can contain up to 100,000 UTF-8 bytes.
- This first version does not support rename or delete actions.
