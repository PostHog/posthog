import {
  createStack,
  extendStack,
  fetchPullRequestRefs,
  formatStack,
  getStack,
  listStacks,
  MAX_STACK_PULL_REQUESTS,
  MIN_STACK_SIZE,
  type StackCtx,
  summarizeStackList,
  unstack,
  validateStackChain,
} from "@posthog/git/stacks";
import { z } from "zod";
import type {
  SignedCommitToolCtx,
  SignedCommitToolResult,
} from "../../signed-commit-shared";
import { qualifiedLocalToolName } from "../registry";
import { defineSignedGitTool } from "./signed-git-tool";

export const GH_STACK_TOOL_NAME = "gh_stack";
export const GH_STACK_QUALIFIED_TOOL_NAME =
  qualifiedLocalToolName(GH_STACK_TOOL_NAME);

export const GH_STACK_TOOL_DESCRIPTION =
  "Manage GitHub native stacked pull requests — an ordered chain where each PR targets the " +
  "branch of the PR below it. Use this instead of the `gh stack` CLI, whose publishing " +
  "commands (`submit`, `sync`, `push`, `link`) all run `git push` and are therefore blocked " +
  "here. Build the layers first: commit each one with `git_signed_commit` (passing `branch`), " +
  "then open its PR with `gh pr create --base <branch of the layer below>`. Then call this " +
  'with operation "create" and the PR numbers ordered bottom to top to link them into a ' +
  'stack. "extend" appends new layers to an existing stack, "view" reads stacks, and ' +
  '"unstack" detaches the unmerged layers. Never merges anything.';

export const ghStackToolSchema = {
  operation: z
    .enum(["view", "create", "extend", "unstack"])
    .describe(
      'What to do: "view" reads a stack (or lists the repo\'s stacks), "create" links pull ' +
        'requests into a new stack, "extend" appends to one, "unstack" dissolves one.',
    ),
  pull_requests: z
    .array(z.number().int().positive())
    .optional()
    .describe(
      'PR numbers ordered bottom to top. Required for "create" (every layer, at least two) ' +
        'and "extend" (only the new layers). For "view", a single number finds the stack ' +
        "containing that PR.",
    ),
  stack: z
    .number()
    .int()
    .positive()
    .optional()
    .describe(
      'Stack number, as shown on the PR. Required for "extend" and "unstack"; optional for ' +
        '"view", which lists every stack in the repository without it.',
    ),
  cwd: z
    .string()
    .optional()
    .describe(
      "Path to the git checkout whose origin remote names the repository; defaults to the " +
        "session's working directory. Relative paths resolve against the session cwd.",
    ),
};

interface GhStackInput {
  operation: "view" | "create" | "extend" | "unstack";
  pull_requests?: number[];
  stack?: number;
}

function ok(text: string): SignedCommitToolResult {
  return { content: [{ type: "text", text }] };
}

function fail(text: string): SignedCommitToolResult {
  return { content: [{ type: "text", text }], isError: true };
}

function checkPayload(
  prs: readonly number[],
  minimum: number,
  operation: string,
): string | null {
  if (prs.length < minimum) {
    return (
      `${GH_STACK_TOOL_NAME} "${operation}" needs \`pull_requests\` with at least ` +
      `${minimum} PR number(s), ordered bottom to top.`
    );
  }
  if (prs.length > MAX_STACK_PULL_REQUESTS) {
    return `A stack takes at most ${MAX_STACK_PULL_REQUESTS} pull requests.`;
  }
  if (new Set(prs).size !== prs.length) {
    return "`pull_requests` contains the same PR twice; a stack is a linear chain.";
  }
  return null;
}

async function checkChain(
  ctx: StackCtx,
  chain: readonly number[],
): Promise<string | null> {
  const refs = await fetchPullRequestRefs(ctx, chain);
  return validateStackChain(refs);
}

async function runGhStack(
  ctx: SignedCommitToolCtx,
  input: GhStackInput,
): Promise<SignedCommitToolResult> {
  const stackCtx: StackCtx = { cwd: ctx.cwd, token: ctx.token };
  const prs = input.pull_requests ?? [];
  try {
    switch (input.operation) {
      case "view": {
        if (input.stack !== undefined) {
          return ok(formatStack(await getStack(stackCtx, input.stack)));
        }
        const stacks = await listStacks(stackCtx, prs[0]);
        if (prs[0] === undefined) return ok(summarizeStackList(stacks));
        return ok(
          stacks.length === 0
            ? `No stack contains #${prs[0]}.`
            : stacks.map(formatStack).join("\n\n"),
        );
      }
      case "create": {
        const problem =
          checkPayload(prs, MIN_STACK_SIZE, "create") ??
          (await checkChain(stackCtx, prs));
        if (problem) return fail(problem);
        return ok(
          `Created the stack.\n${formatStack(await createStack(stackCtx, prs))}`,
        );
      }
      case "extend": {
        if (input.stack === undefined) {
          return fail(
            `${GH_STACK_TOOL_NAME} "extend" needs \`stack\`, the number of the stack to append to.`,
          );
        }
        const payloadProblem = checkPayload(prs, 1, "extend");
        if (payloadProblem) return fail(payloadProblem);
        const top = (await getStack(stackCtx, input.stack)).pull_requests.at(
          -1,
        );
        const problem = await checkChain(
          stackCtx,
          top ? [top.number, ...prs] : prs,
        );
        if (problem) return fail(problem);
        return ok(
          `Extended the stack.\n${formatStack(
            await extendStack(stackCtx, input.stack, prs),
          )}`,
        );
      }
      case "unstack": {
        if (input.stack === undefined) {
          return fail(
            `${GH_STACK_TOOL_NAME} "unstack" needs \`stack\`, the number of the stack to dissolve.`,
          );
        }
        const remaining = await unstack(stackCtx, input.stack);
        return ok(
          remaining === null
            ? `Dissolved stack #${input.stack}.`
            : `Detached the unmerged layers; merged or queued ones stay.\n${formatStack(remaining)}`,
        );
      }
    }
  } catch (err) {
    return fail(err instanceof Error ? err.message : String(err));
  }
}

export const ghStackTool = defineSignedGitTool({
  name: GH_STACK_TOOL_NAME,
  description: GH_STACK_TOOL_DESCRIPTION,
  schema: ghStackToolSchema,
  // Few runs stack, so keep the schema out of every cloud run's context.
  alwaysLoad: false,
  run: runGhStack,
});
