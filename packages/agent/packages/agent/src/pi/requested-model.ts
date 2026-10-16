// A `--model` names a PostHog model, with or without its `posthog/` prefix, or `<provider>/<model>` from one of
// pi's own providers, such as a ChatGPT login's `openai-codex/gpt-5.5`. PostHog ids can carry a slash too
// (`moonshotai/kimi-k3`), so PostHog is asked first.
export function resolveRequestedModel<Model>(
  getModel: (provider: string, id: string) => Model | undefined,
  requested: string,
): Model {
  const id = requested.replace(/^posthog\//, "");
  const found = getModel("posthog", id);
  if (found) return found;
  const slash = id.indexOf("/");
  const fromProvider =
    slash > 0 ? getModel(id.slice(0, slash), id.slice(slash + 1)) : undefined;
  if (fromProvider) return fromProvider;
  throw new Error(`Model not found: ${requested}`);
}
