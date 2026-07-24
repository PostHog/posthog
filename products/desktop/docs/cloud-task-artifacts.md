# Cloud task artifacts

Cloud agents run with `/tmp/workspace` as the sandbox workspace. A repository task uses `/tmp/workspace/repos/<owner>/<repo>` as its working directory; a repository-free task uses `/tmp/workspace` directly. Claude and Codex receive the same working directory, so artifact paths do not vary by model or adapter.

Files left in the sandbox filesystem are temporary and cannot be downloaded after the sandbox is released. Agents should call the `upload_artifact` tool for every non-code deliverable they create. The tool accepts files inside the session working directory, uploads them directly to task object storage, and registers them as `output` artifacts on the task run. Registered artifacts are available through the existing task artifact download endpoint.

Repository changes should continue to be delivered through git rather than duplicated as task artifacts. A single uploaded artifact is limited to 30 MB.
