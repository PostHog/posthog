import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { type Billing, localHarnessFor } from "./billing";
import { CHATGPT_MODEL } from "./chatgpt";
import { type Effort, modelWithEffort, shortModelName } from "./models";

const PAYER: Record<Billing, string> = {
  posthog: "PostHog billing",
  chatgpt: "ChatGPT subscription",
  anthropic: "Anthropic subscription",
};

// What an empty chat shows above its composer: the model, who pays, and where it runs.
export function bannerLines(input: {
  place: "local" | "cloud";
  cwd: string;
  home: string;
  repositories: string[];
  billing: Billing;
  model: string | undefined;
}): string[] {
  const where =
    input.place === "local"
      ? input.cwd.startsWith(input.home)
        ? `~${input.cwd.slice(input.home.length)}`
        : input.cwd
      : ["Cloud run", ...input.repositories].join(" · ");
  return [
    "PostHog",
    [input.model, PAYER[input.billing]].filter(Boolean).join(" • "),
    where,
  ];
}

// The model a new chat starts on: pi's from the harness, Claude Code's from the user's own settings, Codex's unknown.
export function startingModel(
  billing: Billing,
  place: "local" | "cloud",
  piModel: string | undefined,
  claude: { model?: string; effortLevel?: string } = claudeSettings(),
): string | undefined {
  if (billing === "posthog") return piModel;
  if (billing === "chatgpt")
    return place === "local"
      ? shortModelName(CHATGPT_MODEL.split("/")[1])
      : undefined;
  if (place === "local" && localHarnessFor(billing) !== "claude")
    return piModel;
  return claude.model
    ? modelWithEffort(
        shortModelName(claude.model),
        claude.effortLevel as Effort | undefined,
      )
    : undefined;
}

function claudeSettings(): { model?: string; effortLevel?: string } {
  try {
    return JSON.parse(
      readFileSync(join(homedir(), ".claude", "settings.json"), "utf8"),
    ) as { model?: string; effortLevel?: string };
  } catch {
    return {};
  }
}
