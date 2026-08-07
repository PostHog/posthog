# Cloud task artifacts

Cloud agents run with `/tmp/workspace` as the sandbox workspace. A repository task uses `/tmp/workspace/repos/<owner>/<repo>` as its working directory; a repository-free task uses `/tmp/workspace` directly. Claude and Codex receive the same working directory, so artifact paths do not vary by model or adapter.

Files left in the sandbox filesystem are temporary and cannot be downloaded after the sandbox is released. Agents should call the `upload_artifact` tool for every non-code deliverable they create. The tool accepts files inside the session working directory, uploads them directly to task object storage, and registers them as `output` artifacts on the task run. Registered artifacts are available through the existing task artifact download endpoint.

On success the tool returns a presigned download URL for the uploaded file (minted by the finalize-upload endpoint), so an agent can link to the artifact directly in its final response. The URL is time-limited and not persisted on the run manifest; re-fetch the artifact through the download endpoint for a durable link.

Repository changes should continue to be delivered through git rather than duplicated as task artifacts. A single uploaded artifact is limited to 30 MB.

The desktop app runs scripts embedded in HTML artifacts inside an isolated preview process. The preview cannot access Node.js, Electron, PostHog credentials, remote resources, downloads, or device permissions. Use **Stop preview** if a script becomes unresponsive, then use **Restart preview** to load it in a fresh process.

## Versions and dismissal

Uploading a file under a name the run already has does not add a second file. Every upload stays on the manifest as its own entry, and clients group entries by name into one file with a version history: the newest upload is what the app shows, and the earlier ones sit behind a version picker on the row. That is how an agent revises a deliverable — upload it again under the same name.

A user can dismiss a file they don't want to see. `POST .../runs/<run_id>/artifacts/dismiss/` takes `artifact_ids` and a `dismissed` boolean, and stamps `dismissed_at` on each named manifest entry. Nothing is deleted from object storage, and clients only hide a file once every version of it is dismissed, so dismissing the current version cannot resurface the one it replaced. Passing `dismissed: false` restores the file.
