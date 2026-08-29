import { mapWithConcurrency } from "./concurrency";
import { execGhWithRetry, type GhExecResult } from "./gh";
import { ghTokenEnv, resolveRepoNameWithOwner } from "./signed-commit";

/**
 * GitHub native stacked pull requests, driven through the Stacks REST API.
 * The `gh stack` CLI cannot drive one from the cloud sandbox: everything that
 * publishes a stack pushes, and pushing is blocked there. These endpoints only
 * link pull requests that already exist.
 */

const STACKS_API_TIMEOUT_MS = 30_000;

// Matches the staged-blob read limit in signed-commit.ts.
const PR_REF_CONCURRENCY = 16;

// An active repository holds hundreds of stacks — ~10k tokens unrendered.
const STACK_LIST_LIMIT = 20;

export const MIN_STACK_SIZE = 2;
export const MAX_STACK_PULL_REQUESTS = 100;

export interface StackCtx {
  cwd: string;
  token: string;
}

export interface StackPullRequest {
  number: number;
  state: string;
  draft: boolean;
  merged_at: string | null;
  head: { ref: string; sha: string };
}

export interface Stack {
  id: number;
  number: number;
  url: string;
  base: { ref: string };
  open: boolean;
  /** Ordered bottom to top. */
  pull_requests: StackPullRequest[];
}

export interface PullRequestRefs {
  number: number;
  headRef: string;
  baseRef: string;
}

/**
 * Every layer must target the head branch of the layer below it. Checked here
 * because GitHub answers a broken chain with an opaque 422. Layers come bottom
 * to top, with the existing top layer first when extending.
 */
export function validateStackChain(
  prs: readonly PullRequestRefs[],
): string | null {
  for (let i = 1; i < prs.length; i++) {
    const below = prs[i - 1];
    const above = prs[i];
    if (above.baseRef === below.headRef) continue;
    // Names the branch as data, not a runnable command: refs may legally hold
    // `;`, `$()`, and backticks, and an agent runs what it is handed.
    return (
      `#${above.number} targets '${above.baseRef}', but the layer below it (#${below.number}) ` +
      `is on '${below.headRef}'. Every layer must target the branch of the layer below it. ` +
      `Retarget #${above.number} onto that branch with \`gh pr edit\`, then retry.`
    );
  }
  return null;
}

/** A 404 means the repo has stacks turned off far more often than a bad URL. */
export function stacksApiError(res: GhExecResult, action: string): string {
  const detail = (res.stderr || res.error || res.stdout).trim();
  if (/HTTP 404/.test(detail)) {
    return (
      `${action} failed: the Stacks API returned 404. Either stacked pull requests are not ` +
      `enabled for this repository, or the stack number does not exist. Do not retry without ` +
      `checking which — \`gh_stack\` with operation "view" lists the repository's stacks.`
    );
  }
  return `${action} failed: ${detail}`;
}

export function formatStack(stack: Stack): string {
  const layers = stack.pull_requests
    .map((pr, i) => `  ${i + 1}. #${pr.number} ${pr.head.ref}${prState(pr)}`)
    .join("\n");
  return (
    `Stack #${stack.number} onto ${stack.base.ref} ` +
    `(${stack.open ? "open" : "closed"}), bottom to top:\n${layers}`
  );
}

/**
 * Renders the unfiltered browse: open stacks only, capped, and explicit about
 * what it dropped, since a silent cut reads as the whole set.
 */
export function summarizeStackList(stacks: readonly Stack[]): string {
  if (stacks.length === 0) return "No stacks in this repository.";

  const open = stacks.filter((s) => s.open);
  const shown = open.slice(0, STACK_LIST_LIMIT);
  const omitted: string[] = [];
  if (open.length > shown.length) {
    omitted.push(`${open.length - shown.length} more open`);
  }
  if (stacks.length > open.length) {
    omitted.push(`${stacks.length - open.length} closed`);
  }

  const body =
    shown.length === 0
      ? "No open stacks in this repository."
      : shown.map(formatStack).join("\n\n");
  if (omitted.length === 0) return body;
  return (
    `${body}\n\nNot shown: ${omitted.join(", ")}. ` +
    "Pass `stack` or `pull_requests` to read one directly."
  );
}

function prState(pr: StackPullRequest): string {
  if (pr.merged_at) return " — merged";
  if (pr.state !== "open") return ` — ${pr.state}`;
  return pr.draft ? " — draft" : "";
}

async function stacksApi(
  ctx: StackCtx,
  args: string[],
  action: string,
  body?: unknown,
): Promise<string> {
  const res = await execGhWithRetry(
    args,
    {
      cwd: ctx.cwd,
      env: ghTokenEnv(ctx.token),
      timeoutMs: STACKS_API_TIMEOUT_MS,
      // `pull_requests` is an array of integers, which `-f` would send as strings.
      ...(body === undefined ? {} : { input: JSON.stringify(body) }),
    },
    { maxAttempts: 3 },
  );
  if (res.exitCode !== 0) {
    throw new Error(stacksApiError(res, action));
  }
  return res.stdout;
}

export async function listStacks(
  ctx: StackCtx,
  pullRequest?: number,
): Promise<Stack[]> {
  const repo = await resolveRepoNameWithOwner(ctx.cwd);
  const filter =
    pullRequest === undefined ? "" : `&pull_request=${pullRequest}`;
  const stdout = await stacksApi(
    ctx,
    [
      "api",
      `/repos/${repo}/stacks?per_page=100${filter}`,
      "--paginate",
      "--slurp",
    ],
    "Listing stacks",
  );
  // --slurp collects one array per page, so the pages need flattening.
  return (JSON.parse(stdout) as Stack[][]).flat();
}

export async function getStack(
  ctx: StackCtx,
  stackNumber: number,
): Promise<Stack> {
  const repo = await resolveRepoNameWithOwner(ctx.cwd);
  const stdout = await stacksApi(
    ctx,
    ["api", `/repos/${repo}/stacks/${stackNumber}`],
    `Reading stack #${stackNumber}`,
  );
  return JSON.parse(stdout) as Stack;
}

export async function fetchPullRequestRefs(
  ctx: StackCtx,
  numbers: readonly number[],
): Promise<PullRequestRefs[]> {
  const repo = await resolveRepoNameWithOwner(ctx.cwd);
  return mapWithConcurrency(numbers, PR_REF_CONCURRENCY, async (number) => {
    const stdout = await stacksApi(
      ctx,
      [
        "api",
        `/repos/${repo}/pulls/${number}`,
        "--jq",
        "{headRef: .head.ref, baseRef: .base.ref}",
      ],
      `Reading pull request #${number}`,
    );
    return {
      number,
      ...(JSON.parse(stdout) as Omit<PullRequestRefs, "number">),
    };
  });
}

export async function createStack(
  ctx: StackCtx,
  pullRequests: readonly number[],
): Promise<Stack> {
  const repo = await resolveRepoNameWithOwner(ctx.cwd);
  const stdout = await stacksApi(
    ctx,
    ["api", "-X", "POST", `/repos/${repo}/stacks`, "--input", "-"],
    "Creating the stack",
    { pull_requests: pullRequests },
  );
  return JSON.parse(stdout) as Stack;
}

export async function extendStack(
  ctx: StackCtx,
  stackNumber: number,
  pullRequests: readonly number[],
): Promise<Stack> {
  const repo = await resolveRepoNameWithOwner(ctx.cwd);
  const stdout = await stacksApi(
    ctx,
    [
      "api",
      "-X",
      "POST",
      `/repos/${repo}/stacks/${stackNumber}/add`,
      "--input",
      "-",
    ],
    `Extending stack #${stackNumber}`,
    { pull_requests: pullRequests },
  );
  return JSON.parse(stdout) as Stack;
}

/** Resolves to null when the whole stack is gone; the API answers 204 for that. */
export async function unstack(
  ctx: StackCtx,
  stackNumber: number,
): Promise<Stack | null> {
  const repo = await resolveRepoNameWithOwner(ctx.cwd);
  const stdout = await stacksApi(
    ctx,
    ["api", "-X", "POST", `/repos/${repo}/stacks/${stackNumber}/unstack`],
    `Unstacking stack #${stackNumber}`,
  );
  return stdout.trim() ? (JSON.parse(stdout) as Stack) : null;
}
