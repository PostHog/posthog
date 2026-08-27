import { isAbsolutePath, type SkillSource } from "@posthog/shared";
import Fuse, { type IFuseOptions } from "fuse.js";

export interface CommandLike {
  name: string;
  description?: string;
  localSkill?: {
    name: string;
    source: Exclude<SkillSource, "bundled">;
    path: string;
  };
}

export interface FileItemLike {
  path: string;
  name: string;
  dir: string;
  kind: "file" | "directory";
}

export interface FileSuggestionShape {
  id: string;
  label: string;
  description?: string;
  filename?: string;
  path: string;
  kind?: "file" | "directory";
  chipType?: "file" | "folder";
}

export interface CommandSuggestionShape<T extends CommandLike> {
  id: string;
  label: string;
  description?: string;
  skillPath?: string;
  skillSource?: Exclude<SkillSource, "bundled">;
  skillName?: string;
  command: T;
}

const COMMAND_FUSE_OPTIONS: IFuseOptions<CommandLike> = {
  keys: [
    { name: "name", weight: 0.7 },
    { name: "description", weight: 0.3 },
  ],
  threshold: 0.3,
  includeScore: true,
};

export function searchCommands<T extends CommandLike>(
  commands: T[],
  query: string,
): T[] {
  if (!query.trim()) {
    return commands;
  }

  const fuse = new Fuse(commands, COMMAND_FUSE_OPTIONS);
  const results = fuse.search(query);

  const lowerQuery = query.toLowerCase();
  results.sort((a, b) => {
    const aStartsWithQuery = a.item.name.toLowerCase().startsWith(lowerQuery);
    const bStartsWithQuery = b.item.name.toLowerCase().startsWith(lowerQuery);

    if (aStartsWithQuery && !bStartsWithQuery) return -1;
    if (!aStartsWithQuery && bStartsWithQuery) return 1;
    return (a.score ?? 0) - (b.score ?? 0);
  });

  return results.map((result) => result.item);
}

export function mergeCommands<T extends CommandLike>(
  codeCommands: T[],
  agentCommands: T[],
): T[] {
  const merged = [...codeCommands, ...agentCommands];
  return [...new Map(merged.map((cmd) => [cmd.name, cmd])).values()];
}

export function shapeCommandSuggestions<T extends CommandLike>(
  commands: T[],
): CommandSuggestionShape<T>[] {
  return commands.map((cmd) => ({
    id: cmd.localSkill?.path ?? cmd.name,
    label: cmd.name,
    description: cmd.description,
    skillPath: cmd.localSkill?.path,
    skillSource: cmd.localSkill?.source,
    skillName: cmd.localSkill?.name,
    command: cmd,
  }));
}

export function parentDirLabel(dir: string, name: string): string {
  const parent = dir.split("/").filter(Boolean).pop();
  return parent ? `${parent}/${name}` : name;
}

export function getAbsolutePathSuggestion(
  query: string,
): FileSuggestionShape | null {
  if (!isAbsolutePath(query)) return null;
  if (!/\.\w+$/.test(query)) return null;

  const parts = query.split("/");
  const name = parts.pop() ?? query;
  const dir = parts.join("/");
  return {
    id: query,
    label: parentDirLabel(dir, name),
    description: dir || undefined,
    filename: name,
    path: query,
  };
}

export function shapeFileSuggestions(
  matched: FileItemLike[],
  repoPath: string,
  absoluteMatch: FileSuggestionShape | null,
): FileSuggestionShape[] {
  const results: FileSuggestionShape[] = matched.map((file) => {
    const isDirectory = file.kind === "directory";
    return {
      id: file.path,
      label: parentDirLabel(file.dir, file.name),
      description: file.dir || undefined,
      filename: file.name,
      path: file.path,
      kind: file.kind,
      chipType: isDirectory ? "folder" : "file",
    };
  });

  if (
    absoluteMatch &&
    !results.some((r) => `${repoPath}/${r.id}` === absoluteMatch.id)
  ) {
    results.unshift(absoluteMatch);
  }

  return results;
}
