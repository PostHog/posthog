import { BRANCH_PREFIX } from "@posthog/shared";

export function sanitizeBranchName(input: string): string {
  return input.replace(/ /g, "-");
}

export function validateBranchName(name: string): string | null {
  if (name === "") return null;

  // biome-ignore lint/suspicious/noControlCharactersInRegex: intentionally matching ASCII control characters forbidden by git
  if (/[\x00-\x1f\x7f]/.test(name)) {
    return "Branch name cannot contain control characters.";
  }

  if (name.includes("..")) {
    return 'Branch name cannot contain "..".';
  }

  if (/[~^:?*[\]\\]/.test(name)) {
    return "Branch name cannot contain ~, ^, :, ?, *, [, ], or \\.";
  }

  if (name.includes(" ")) {
    return "Branch name cannot contain spaces.";
  }

  if (name.startsWith(".") || name.endsWith(".")) {
    return "Branch name cannot start or end with a dot.";
  }

  if (name.endsWith(".lock")) {
    return 'Branch name cannot end with ".lock".';
  }

  if (name.includes("@{")) {
    return 'Branch name cannot contain "@{".';
  }

  if (name === "@") {
    return 'Branch name cannot be "@".';
  }

  if (name.includes("//")) {
    return 'Branch name cannot contain "//".';
  }

  const components = name.split("/");
  for (const component of components) {
    if (component.startsWith(".") || component.endsWith(".")) {
      return "Path components cannot start or end with a dot.";
    }
  }

  return null;
}

export function deriveBranchName(title: string, fallbackId: string): string {
  const slug = title
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60)
    .replace(/-$/, "");

  if (!slug) return `${BRANCH_PREFIX}task-${fallbackId}`;
  return `${BRANCH_PREFIX}${slug}`;
}

export function suggestBranchName(
  title: string,
  fallbackId: string,
  existingBranches: string[],
): string {
  const base = deriveBranchName(title, fallbackId);

  if (!existingBranches.includes(base)) return base;

  let n = 2;
  while (existingBranches.includes(`${base}-${n}`)) n++;
  return `${base}-${n}`;
}
