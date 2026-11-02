import type { Billing } from "./billing";

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
