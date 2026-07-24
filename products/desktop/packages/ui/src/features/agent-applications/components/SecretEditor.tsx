import { CheckCircleIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/ui/primitives/Button";
import { Flex, Text, TextField } from "@radix-ui/themes";
import { useState } from "react";
import { useAgentEnvKeyMutations } from "../hooks/useAgentEnvKeyMutations";

/**
 * Inline set/rotate/clear for one encrypted env key. The value is write-only —
 * posted straight to `env_keys` PUT, never read back. On success the env-keys
 * list refetches, flipping set/not-set status across the explorer.
 *
 * A set secret shows only its status + a Rotate affordance (the input stays
 * hidden until you opt in) and Clear is a two-step confirm — clearing a live
 * credential is destructive and must never be a single click.
 */
export function SecretEditor({
  idOrSlug,
  revisionId,
  keyName,
  isSet,
}: {
  idOrSlug: string;
  revisionId: string;
  keyName: string;
  isSet: boolean;
}) {
  const { setKey, clearKey } = useAgentEnvKeyMutations(idOrSlug, revisionId);
  // For a set secret the input is hidden until the user chooses to rotate.
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [justSaved, setJustSaved] = useState(false);

  const busy = setKey.isPending || clearKey.isPending;
  const showInput = !isSet || editing;

  function save() {
    if (!value.trim()) return;
    setKey.mutate(
      { key: keyName, value },
      {
        onSuccess: () => {
          setValue("");
          setEditing(false);
          setJustSaved(true);
          setTimeout(() => setJustSaved(false), 2000);
        },
      },
    );
  }

  function cancelEdit() {
    setEditing(false);
    setValue("");
  }

  function confirmClear() {
    clearKey.mutate(
      { key: keyName },
      { onSettled: () => setConfirmingClear(false) },
    );
  }

  return (
    <Flex direction="column" gap="2" className="mt-2">
      {showInput ? (
        <>
          <Text className="text-[11px] text-gray-10 uppercase tracking-wide">
            {isSet ? "Rotate value" : "Set value"}
          </Text>
          <TextField.Root
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="paste secret value"
            autoComplete="off"
            spellCheck={false}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
            }}
          />
          {isSet ? (
            <Text className="text-[11px] text-gray-10">
              A value is already set — saving will replace it.
            </Text>
          ) : null}
          {setKey.isError ? (
            <Text className="text-(--red-11) text-[11px]">
              {setKey.error?.message ?? "Couldn't save"}
            </Text>
          ) : null}
          <Flex align="center" gap="2">
            <Button
              size="1"
              color="green"
              onClick={save}
              disabled={busy || !value.trim()}
              loading={setKey.isPending}
            >
              {isSet ? "Save new value" : "Set"}
            </Button>
            {isSet ? (
              <Button
                size="1"
                variant="soft"
                color="gray"
                onClick={cancelEdit}
                disabled={busy}
              >
                Cancel
              </Button>
            ) : null}
          </Flex>
        </>
      ) : confirmingClear ? (
        <div className="rounded-(--radius-2) border border-(--red-6) bg-(--red-2) px-3 py-2.5">
          <Text className="block text-[12px] text-gray-12">
            Clear{" "}
            <code className="[font-family:var(--font-mono)]">{keyName}</code>?
            This deletes the stored value — the agent will stop being able to
            read it until you set it again.
          </Text>
          {clearKey.isError ? (
            <Text className="mt-1 block text-(--red-11) text-[11px]">
              {clearKey.error?.message ?? "Couldn't clear"}
            </Text>
          ) : null}
          <Flex gap="2" className="mt-2">
            <Button
              size="1"
              color="red"
              onClick={confirmClear}
              disabled={busy}
              loading={clearKey.isPending}
            >
              Yes, clear it
            </Button>
            <Button
              size="1"
              variant="soft"
              color="gray"
              onClick={() => setConfirmingClear(false)}
              disabled={busy}
            >
              Cancel
            </Button>
          </Flex>
        </div>
      ) : (
        <Flex align="center" gap="2">
          <Button
            size="1"
            variant="soft"
            color="gray"
            onClick={() => setEditing(true)}
          >
            Rotate
          </Button>
          <Button
            size="1"
            variant="soft"
            color="red"
            onClick={() => setConfirmingClear(true)}
          >
            Clear
          </Button>
          {justSaved ? (
            <Flex align="center" gap="1" className="text-(--green-11)">
              <CheckCircleIcon size={14} />
              <Text className="text-[12px]">Saved</Text>
            </Flex>
          ) : null}
        </Flex>
      )}
      <Text className="text-[11px] text-gray-10 leading-snug">
        The value is never shown again. It's encrypted at rest and only read by
        the agent at runtime.
      </Text>
    </Flex>
  );
}
