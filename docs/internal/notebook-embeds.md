# Notebook embeds

Notebook `Embed` blocks accept absolute HTTP or HTTPS URLs.
Other URLs show a placeholder instead of an iframe.

The production markdown notebook registry renders these blocks through `NotebookNodeEmbed`.
The shared markdown notebook component also has a default embed view.
Both views withhold `allow-same-origin` when the target URL has the same origin as the PostHog page.
Third-party targets keep their existing sandbox permissions.
The production node also retains its existing popup and form permissions.

Same-origin embeds cannot access the parent document or origin-bound browser storage.
Pages that require that access, including embedded pages that use browser storage during startup, may not work inside the frame.
Open those pages directly instead.

`MarkdownNotebookV2RendererUI.test.tsx` covers the production registry path.
`registry.test.tsx` covers the default view.
