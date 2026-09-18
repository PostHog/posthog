import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";

const AUTO_PUBLISH_SYSTEM_PROMPT = [
  "The user has auto-publish enabled for this cloud run.",
  "After completing and verifying code changes, create a `posthog/` branch, stage the changes, use the `git_signed_commit` tool to create a signed commit, and open a draft pull request with `gh pr create --draft`. Do not stop with local changes waiting for review.",
  "Do not use `git commit` or `git push`. If this task already has an open pull request for the same work, continue on that PR instead of opening another one.",
  "Default to a single pull request. When a change splits into independently reviewable layers, you may stack instead: commit each layer with `git_signed_commit` onto its own branch, open each pull request with `gh pr create --base <branch of the layer below>`, then link them with the `gh_stack` tool. Do not use the `gh stack` CLI, whose publishing commands push.",
].join("\n");

export function createAutoPublishExtension(): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    pi.on("before_agent_start", (event) => ({
      systemPrompt: `${event.systemPrompt}\n\n${AUTO_PUBLISH_SYSTEM_PROMPT}`,
    }));
  };
}
