export function buildWorkspacePersistenceInstructions(): string {
  return `## Files that persist when the session pauses
A long session can pause and resume in a new sandbox. Only /tmp/workspace is kept. All other files are erased, including other /tmp paths, your home directory, and installed system packages.
- Keep files you need later (notes, plans, scripts, data) in /tmp/workspace/scratch/, not in the repository checkout.
- Do not keep them in node_modules, .venv, .cache, or other cache folders. The system can delete these folders.
- After a resume, install system packages again.`;
}
