# Cloud task artifacts

Cloud agents run with `/tmp/workspace` as the sandbox workspace. A repository task uses `/tmp/workspace/repos/<owner>/<repo>` as its working directory; a repository-free task uses `/tmp/workspace` directly. Claude and Codex receive the same working directory, so artifact paths do not vary by model or adapter.

Files left in the sandbox filesystem are temporary and cannot be downloaded after the sandbox is released. Agents should call the `upload_artifact` tool for every non-code deliverable they create. The tool accepts files inside the session working directory, uploads them directly to task object storage, and registers them as `output` artifacts on the task run. Registered artifacts are available through the existing task artifact download endpoint.

On success the tool returns a presigned download URL for the uploaded file (minted by the finalize-upload endpoint), so an agent can link to the artifact directly in its final response. The URL is time-limited and not persisted on the run manifest; re-fetch the artifact through the download endpoint for a durable link.

Agent output uploads also create a stable task artifact and its first version. Each later save uploads a new immutable run artifact and records it as the next version of that stable artifact. To revise an artifact with `upload_artifact`, pass the stable artifact ID and the current version ID returned by the artifact tools. The save is rejected if another user or agent created a newer version first.

PostHog Code can edit UTF-8 text artifacts up to 500 KB. This includes Markdown, HTML, CSV, JSON, configuration files, and source code. Larger text files and binary files remain downloadable and keep their version history, but they are not editable in the built-in editor.

Repository changes should continue to be delivered through git rather than duplicated as task artifacts. A single uploaded artifact is limited to 30 MB.
