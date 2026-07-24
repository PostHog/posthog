const HEADER_RE = /^---\s*(.+?)\s*---\s*$/;
const SKILL_PATH_RE = /^skills\/([a-z0-9-]+)\/SKILL\.md$/;

export interface ParsedBundle {
  agent_md?: string;
  skills?: { id: string; body: string }[];
}

/**
 * Splits a fenced paste — alternating `--- <path> ---` headers and bodies —
 * into the import payload the server accepts. The format is deliberately
 * simple so the source files can be cat'd together as-is; only `agent.md`
 * and `skills/<id>/SKILL.md` are recognised.
 */
export function parseBundleInput(
  input: string,
): { ok: true; value: ParsedBundle } | { ok: false; error: string } {
  const lines = input.replace(/\r\n/g, "\n").split("\n");
  const value: ParsedBundle = {};
  let current: { kind: "agent" } | { kind: "skill"; id: string } | null = null;
  let buf: string[] = [];

  const flush = () => {
    if (!current) return;
    const content = buf.join("\n").replace(/^\n+|\n+$/g, "");
    if (current.kind === "agent") {
      value.agent_md = content;
    } else {
      if (!value.skills) value.skills = [];
      value.skills.push({ id: current.id, body: content });
    }
  };

  for (const line of lines) {
    const m = HEADER_RE.exec(line);
    if (m) {
      flush();
      buf = [];
      const path = m[1];
      if (path === "agent.md") {
        current = { kind: "agent" };
      } else {
        const skill = SKILL_PATH_RE.exec(path);
        if (!skill) {
          return {
            ok: false,
            error: `Unsupported file path: "${path}". Use "agent.md" or "skills/<id>/SKILL.md".`,
          };
        }
        current = { kind: "skill", id: skill[1] };
      }
      continue;
    }
    if (current) buf.push(line);
  }
  flush();

  if (value.agent_md === undefined && !value.skills?.length) {
    return {
      ok: false,
      error:
        "Nothing to import. Add at least one `--- agent.md ---` or `--- skills/<id>/SKILL.md ---` block.",
    };
  }
  return { ok: true, value };
}
