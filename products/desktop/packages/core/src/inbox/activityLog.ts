const SIGNALS_TYPE_LABELS: Record<string, string> = {
  research: "Research",
  implementation: "Implementation",
  repo_selection: "Repo selection",
};

export function humanizeIdentifier(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function taskRunLabel(content: {
  product: string;
  type: string;
}): string {
  return content.product === "signals"
    ? (SIGNALS_TYPE_LABELS[content.type] ?? humanizeIdentifier(content.type))
    : humanizeIdentifier(content.type);
}

export function attributionLabel(artefact: {
  created_by?: { first_name?: string; email: string } | null;
  task_id?: string | null;
}): string | null {
  if (artefact.created_by) {
    return artefact.created_by.first_name?.trim() || artefact.created_by.email;
  }
  return artefact.task_id ? "agent" : null;
}
