import { ArrowSquareOutIcon, ChatCircleIcon } from "@phosphor-icons/react";
import { Flex, Text } from "@radix-ui/themes";
import { useAgentSlackManifest } from "../hooks/useAgentSlackManifest";
import { CopyButton } from "./CopyButton";

/**
 * Deterministic Slack app setup for a slack-triggered agent: the manifest the
 * backend derives from the trigger + tools (scopes + event subscriptions
 * computed), the "create from manifest" link, the live request URLs, and setup
 * notes. Surfaced under the slack trigger's detail.
 */
export function SlackSetupCard({
  idOrSlug,
  revisionId,
}: {
  idOrSlug: string;
  revisionId: string;
}) {
  const { data, isLoading, isError, error } = useAgentSlackManifest(
    idOrSlug,
    revisionId,
  );
  const manifestJson = data ? JSON.stringify(data.manifest, null, 2) : "";
  const interactivity = data
    ? (data.manifest as { settings?: { interactivity?: unknown } }).settings
        ?.interactivity
    : undefined;

  return (
    <section className="mt-3 overflow-hidden rounded-(--radius-2) border border-border">
      <Flex
        align="center"
        gap="2"
        className="border-(--gray-5) border-b bg-(--gray-2) px-4 py-1.5 text-[10.5px] text-gray-10 uppercase tracking-wide"
      >
        <ChatCircleIcon size={13} />
        Slack app setup
      </Flex>
      {isLoading && !data ? (
        <Text className="block px-4 py-3 text-[12px] text-gray-10">
          Generating manifest…
        </Text>
      ) : isError ? (
        <Text className="block px-4 py-3 text-[12px] text-gray-10">
          Could not generate the Slack manifest: {error?.message}
        </Text>
      ) : data ? (
        <Flex direction="column" gap="3" className="px-4 py-3">
          <Text className="text-[11.5px] text-gray-10 leading-snug">
            Paste this manifest into Slack to create the app with the right
            scopes and event subscriptions already filled in — derived from this
            agent's trigger config and tools.
          </Text>
          <Flex align="center" gap="2" wrap="wrap">
            <a
              href="https://api.slack.com/apps?new_app=1"
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-7 items-center gap-1.5 rounded-(--radius-2) bg-(--accent-9) px-2.5 font-medium text-[11.5px] text-white no-underline hover:opacity-90"
            >
              <ArrowSquareOutIcon size={12} />
              Create Slack app from manifest
            </a>
            <CopyButton text={manifestJson} label="Copy manifest" showLabel />
          </Flex>
          <Text className="text-[11.5px] text-gray-10 leading-snug">
            In Slack, choose “From an app manifest”, pick the workspace, then
            paste the JSON below (use the JSON tab).
          </Text>
          <pre className="max-h-80 overflow-auto rounded-(--radius-2) border border-border bg-(--gray-2) p-2.5 text-[11px] leading-relaxed">
            <code className="[font-family:var(--font-mono)]">
              {manifestJson}
            </code>
          </pre>
          <Flex direction="column" gap="1.5" className="text-[11.5px]">
            <RequestUrlRow
              label="Event Subscriptions Request URL"
              url={data.events_url}
            />
            {interactivity ? (
              <RequestUrlRow
                label="Interactivity Request URL"
                url={data.interactivity_url}
              />
            ) : null}
          </Flex>
          {data.notes.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-4 text-[10.5px] text-gray-10">
              {data.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}
        </Flex>
      ) : (
        <Text className="block px-4 py-3 text-[12px] text-gray-10">
          No manifest available.
        </Text>
      )}
    </section>
  );
}

function RequestUrlRow({ label, url }: { label: string; url: string | null }) {
  return (
    <Flex align="baseline" gap="2">
      <Text className="shrink-0 text-gray-10">{label}:</Text>
      {url ? (
        <Flex align="center" gap="1.5" className="min-w-0">
          <code className="truncate [font-family:var(--font-mono)]">{url}</code>
          <CopyButton text={url} />
        </Flex>
      ) : (
        <Text className="text-gray-9 italic">
          not available (no public ingress URL configured)
        </Text>
      )}
    </Flex>
  );
}
