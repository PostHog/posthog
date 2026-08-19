# Cloud task artifacts

Cloud agents run with `/tmp/workspace` as the sandbox workspace. A repository task uses `/tmp/workspace/repos/<owner>/<repo>` as its working directory; a repository-free task uses `/tmp/workspace` directly. Claude and Codex receive the same working directory, so artifact paths do not vary by model or adapter.

Files left in the sandbox filesystem are temporary and cannot be downloaded after the sandbox is released. Agents should call the `upload_artifact` tool for every non-code deliverable they create. The tool accepts files inside the session working directory, uploads them directly to task object storage, and registers them as `output` artifacts on the task run. Registered artifacts are available through the existing task artifact download endpoint.

On success the tool returns a presigned download URL for the uploaded file (minted by the finalize-upload endpoint), so an agent can link to the artifact directly in its final response. The URL is time-limited and not persisted on the run manifest; re-fetch the artifact through the download endpoint for a durable link.

Repository changes should continue to be delivered through git rather than duplicated as task artifacts. A single uploaded artifact is limited to 30 MB.

## PostHog object references

A completed assistant message can reference a PostHog object with an object tag, such as `<insight id="9pQx3">Checkout funnel</insight>`. Desktop extracts these tags after the turn completes and registers them in the same run artifact manifest with `type: reference` and `source: posthog_object`.

Reference artifacts do not upload a file and do not have a storage path, size, or download URL. Their metadata stores the object kind, exact identifier, source message IDs, and occurrence count. Replaying the same completed message updates the existing entry instead of creating another one.

Registration failure does not block the completed turn or replace the current artifact list. Desktop retries when it hydrates the completed turn again, so the client and backend can deploy in either order.

The Artifacts pane shows file and reference artifacts in one list. The Timeline announces a new reference as an added artifact. Both surfaces open the same artifact tab, which resolves the current object data from the active PostHog project.

The desktop app runs scripts embedded in HTML artifacts inside an isolated preview process. The preview cannot access Node.js, Electron, PostHog credentials, remote resources, downloads, or device permissions. Use **Stop preview** if a script becomes unresponsive, then use **Restart preview** to load it in a fresh process.

## Versions and dismissal

Uploading a file under a name the run already has does not add a second file. Every upload stays on the manifest as its own entry, and clients group entries by name into one file with a version history: the newest upload is what the app shows, and the earlier ones sit behind a version picker on the row. An agent revises a deliverable by reading the current latest version, then uploading its revision under the same name.

Users can edit the latest Markdown, HTML, and plain-text version in the app. Saving appends another `output` entry under the same name. It never overwrites the version the user opened, and a confirmation appears if another version arrived during the edit.

A user can dismiss a file they don't want to see. `POST .../runs/<run_id>/artifacts/dismiss/` takes `artifact_ids` and a `dismissed` boolean, and stamps `dismissed_at` on each named manifest entry. Nothing is deleted from object storage, and clients only hide a file once every version of it is dismissed, so dismissing the current version cannot resurface the one it replaced. Passing `dismissed: false` restores the file.
