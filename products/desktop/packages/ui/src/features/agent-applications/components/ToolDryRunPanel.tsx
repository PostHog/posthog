import {
  CheckCircleIcon,
  PlayIcon,
  PlusIcon,
  TrashIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import type { DryRunToolResult } from "@posthog/shared/agent-platform-types";
import { Button } from "@posthog/ui/primitives/Button";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { Flex, IconButton, Text, TextArea, TextField } from "@radix-ui/themes";
import { type ReactNode, useRef, useState } from "react";
import { useDryRunRevisionTool } from "../hooks/useDryRunRevisionTool";

interface SecretRow {
  /** Stable per-row id so React keys survive reordering/removal. */
  id: number;
  name: string;
  value: string;
}

/**
 * Minimal dry-run surface for a persisted tool: an args JSON editor, an optional
 * mock-secrets key/value editor, and a Test button that runs the tool once in a
 * sandbox. The dry-run envelope's `ok` is authoritative (a throwing tool is HTTP
 * 200 with ok:false), and throttled (429) / unavailable (503) are handled as
 * explicit states — no retries, since dry-run is process-capped.
 */
export function ToolDryRunPanel({
  idOrSlug,
  revisionId,
  toolId,
}: {
  idOrSlug: string;
  revisionId: string;
  toolId: string;
}) {
  const dryRun = useDryRunRevisionTool(idOrSlug, revisionId);
  const [argsText, setArgsText] = useState("{}");
  const [argsError, setArgsError] = useState<string | null>(null);
  const [secrets, setSecrets] = useState<SecretRow[]>([]);
  const [result, setResult] = useState<DryRunToolResult | null>(null);
  const nextSecretId = useRef(0);

  function run() {
    let args: unknown;
    try {
      args = argsText.trim() ? JSON.parse(argsText) : {};
    } catch {
      setArgsError("Args must be valid JSON.");
      return;
    }
    setArgsError(null);
    setResult(null);

    const mockSecrets: Record<string, string> = {};
    for (const s of secrets) {
      const name = s.name.trim();
      if (name) mockSecrets[name] = s.value;
    }
    const hasSecrets = Object.keys(mockSecrets).length > 0;

    dryRun.mutate(
      {
        toolId,
        body: { args, ...(hasSecrets ? { mock_secrets: mockSecrets } : {}) },
      },
      { onSuccess: (res) => setResult(res) },
    );
  }

  return (
    <div className="mt-3 rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-3">
      <Text className="block text-[11px] text-gray-10 uppercase tracking-wide [font-family:var(--font-mono)]">
        Dry run
      </Text>
      <Text className="mt-0.5 mb-2 block text-[11px] text-gray-10 leading-snug">
        Runs the saved tool once in a sandbox. Args are passed straight to{" "}
        <code className="[font-family:var(--font-mono)]">actions.default</code>{" "}
        — they aren't validated against the schema.
      </Text>

      <Text className="mb-1 block text-[11px] text-gray-10">Args (JSON)</Text>
      <TextArea
        value={argsText}
        onChange={(e) => setArgsText(e.target.value)}
        rows={5}
        spellCheck={false}
        className="text-[12px] [font-family:var(--font-mono)]"
      />
      {argsError ? (
        <Text className="mt-1 block text-(--red-11) text-[11px]">
          {argsError}
        </Text>
      ) : null}

      <Flex align="center" justify="between" className="mt-3 mb-1">
        <Text className="text-[11px] text-gray-10">
          Mock secrets (optional)
        </Text>
        <Button
          size="1"
          variant="ghost"
          color="gray"
          onClick={() =>
            setSecrets((s) => [
              ...s,
              { id: nextSecretId.current++, name: "", value: "" },
            ])
          }
        >
          <PlusIcon size={12} />
          Add
        </Button>
      </Flex>
      {secrets.length === 0 ? (
        <Text className="block text-[11px] text-gray-9 leading-snug">
          Each entry is the placeholder{" "}
          <code className="[font-family:var(--font-mono)]">
            ctx.secrets.ref("NAME")
          </code>{" "}
          returns in the sandbox. Real secret values never leave the backend.
        </Text>
      ) : (
        <Flex direction="column" gap="1.5">
          {secrets.map((row) => (
            <Flex key={row.id} align="center" gap="2">
              <TextField.Root
                value={row.name}
                placeholder="SECRET_NAME"
                spellCheck={false}
                className="flex-1 text-[12px] [font-family:var(--font-mono)]"
                onChange={(e) =>
                  setSecrets((s) =>
                    s.map((r) =>
                      r.id === row.id ? { ...r, name: e.target.value } : r,
                    ),
                  )
                }
              />
              <TextField.Root
                value={row.value}
                placeholder="placeholder value"
                spellCheck={false}
                className="flex-1 text-[12px] [font-family:var(--font-mono)]"
                onChange={(e) =>
                  setSecrets((s) =>
                    s.map((r) =>
                      r.id === row.id ? { ...r, value: e.target.value } : r,
                    ),
                  )
                }
              />
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                aria-label="Remove secret"
                onClick={() =>
                  setSecrets((s) => s.filter((r) => r.id !== row.id))
                }
              >
                <TrashIcon size={12} />
              </IconButton>
            </Flex>
          ))}
        </Flex>
      )}

      <Flex align="center" gap="2" className="mt-3">
        <Button
          size="1"
          onClick={run}
          disabled={dryRun.isPending}
          loading={dryRun.isPending}
        >
          {!dryRun.isPending ? <PlayIcon size={12} /> : null}
          {dryRun.isPending ? "Running…" : "Test tool"}
        </Button>
      </Flex>

      {dryRun.isError ? (
        <Text className="mt-2 block text-(--red-11) text-[11px]">
          {dryRun.error?.message ?? "Dry run failed."}
        </Text>
      ) : null}

      {result ? <DryRunResult result={result} /> : null}
    </div>
  );
}

function DryRunResult({ result }: { result: DryRunToolResult }) {
  if (result.outcome === "throttled") {
    return (
      <Attn tone="warn">
        <Text className="text-[12px] text-gray-12">
          {result.max_concurrent != null
            ? `Dry-run is busy — the ${result.max_concurrent}-run limit is already in flight. Try again in a moment.`
            : "Dry-run is busy — too many runs in flight. Try again in a moment."}
        </Text>
      </Attn>
    );
  }
  if (result.outcome === "unavailable") {
    return (
      <Attn tone="warn">
        <Text className="text-[12px] text-gray-12">
          Dry-run isn't available on this deployment — the sandbox backend isn't
          configured here.
        </Text>
      </Attn>
    );
  }

  const { envelope } = result;
  return (
    <div className="mt-2">
      <Flex align="center" gap="1.5" className="mb-1">
        {envelope.ok ? (
          <>
            <CheckCircleIcon size={13} className="text-(--green-11)" />
            <Text className="font-medium text-(--green-11) text-[12px]">
              Success
            </Text>
          </>
        ) : (
          <>
            <WarningCircleIcon size={13} className="text-(--red-11)" />
            <Text className="font-medium text-(--red-11) text-[12px]">
              {envelope.error?.code ?? "error"}
            </Text>
          </>
        )}
        <Text className="ml-auto text-[11px] text-gray-10 [font-family:var(--font-mono)]">
          {envelope.duration_ms} ms
        </Text>
      </Flex>
      {envelope.ok ? (
        <CodeBlock>{formatResult(envelope.result)}</CodeBlock>
      ) : (
        <div className="rounded-(--radius-2) border border-(--red-6) bg-(--red-2) px-3 py-2">
          <Text className="block text-[12px] text-gray-12 leading-snug">
            {envelope.error?.message ?? "The tool failed with no message."}
          </Text>
        </div>
      )}
    </div>
  );
}

function formatResult(result: unknown): string {
  if (result === undefined) return "undefined";
  if (typeof result === "string") return result;
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

function Attn({ children, tone }: { children: ReactNode; tone: "warn" }) {
  return (
    <div
      className={`mt-2 rounded-(--radius-2) border px-3 py-2 ${
        tone === "warn" ? "border-(--amber-6) bg-(--amber-2)" : ""
      }`}
    >
      {children}
    </div>
  );
}
