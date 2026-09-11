import { PencilSimple } from "@phosphor-icons/react";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  CATEGORY_LABELS,
  formatHotkeyParts,
  getShortcutsByCategory,
  type ShortcutCategory,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { useInboxAvailable } from "@posthog/ui/features/feature-flags/useInboxAvailable";
import { useQuickAskShortcut } from "@posthog/ui/features/quick-ask/useQuickAskShortcut";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";

function Keycap({ label, size = "md" }: { label: string; size?: "sm" | "md" }) {
  const [pressed, setPressed] = useState(false);
  const isSmall = size === "sm";
  const minW = isSmall ? "22px" : "28px";
  const h = isSmall ? "22px" : "28px";
  const fontSize = isSmall ? "11px" : "13px";
  const shadowSize = isSmall ? "2px" : "3px";

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: cosmetic press animation
    <span
      role="presentation"
      onMouseDown={() => setPressed(true)}
      onMouseUp={() => setPressed(false)}
      onMouseLeave={() => setPressed(false)}
      style={{
        minWidth: minW,
        height: h,
        fontSize,
        fontFamily: "system-ui, -apple-system, sans-serif",
        lineHeight: 1,
        borderBottomWidth: pressed ? "1px" : shadowSize,
        borderBottomColor: "var(--gray-7)",
        transform: pressed
          ? `translateY(${isSmall ? "1px" : "2px"})`
          : "translateY(0)",
        transition:
          "transform 80ms ease-out, border-bottom-width 80ms ease-out",
      }}
      className="box-border inline-flex cursor-pointer select-none items-center justify-center rounded-[6px] border border-(--gray-5) bg-(--gray-3) px-[6px] py-0 font-medium text-(--gray-11)"
    >
      {label}
    </span>
  );
}

interface KeyboardShortcutsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function KeyboardShortcutsSheet({
  open,
  onOpenChange,
}: KeyboardShortcutsSheetProps) {
  const quickAsk = useQuickAskShortcut();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="max-h-[80vh] overflow-hidden sm:max-w-[600px]"
      >
        <DialogHeader className="relative flex-row items-start justify-between">
          <ShortcutsHeader />
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="shrink-0 cursor-pointer [all:unset]"
          >
            <Keycap label="Esc" size="sm" />
          </button>
        </DialogHeader>

        <DialogBody className="max-h-[calc(80vh-120px)]">
          <KeyboardShortcutsList
            leadingGeneralShortcuts={quickAsk ? [quickAsk] : []}
          />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

function ShortcutsHeader() {
  const triggerParts = formatHotkeyParts("mod+/");

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-3">
        <DialogTitle className="text-2xl leading-[1.2]">
          Keyboard Combos
        </DialogTitle>
        <div className="flex items-center gap-1">
          {triggerParts.map((part) => (
            <Keycap key={part} label={part} />
          ))}
        </div>
      </div>
      <DialogDescription>
        Your cheat codes for shipping faster
      </DialogDescription>
    </div>
  );
}

export interface LeadingShortcutRow {
  id: string;
  description: string;
  /** Hotkey format ("alt+space"), same as the static shortcut table. */
  keys: string;
  onEdit?: () => void;
}

export function KeyboardShortcutsList({
  leadingGeneralShortcuts = [],
}: {
  /** Dynamic rows (the quick-ask shortcut) shown first under General. */
  leadingGeneralShortcuts?: LeadingShortcutRow[];
} = {}) {
  // Several keys change owner with the layout, so the sheet has to know which
  // one is on rather than listing keys nothing handles.
  const channelsLayout = useChannelsLayout();
  const inboxAvailable = useInboxAvailable();
  const shortcutsByCategory = useMemo(
    () =>
      getShortcutsByCategory({
        channelsLayout,
        inboxEnabled: inboxAvailable,
      }),
    [channelsLayout, inboxAvailable],
  );

  const categoryOrder: ShortcutCategory[] = [
    "general",
    "navigation",
    "panels",
    "editor",
  ];

  return (
    <Flex direction="column" gap="5">
      {categoryOrder.map((category) => {
        const shortcuts = shortcutsByCategory[category];
        if (shortcuts.length === 0) return null;

        const uniqueShortcuts = shortcuts.reduce(
          (acc, shortcut) => {
            const existing = acc.find(
              (s) => s.description === shortcut.description,
            );
            if (!existing) {
              acc.push(shortcut);
            }
            return acc;
          },
          [] as typeof shortcuts,
        );

        return (
          <Flex key={category} direction="column" gap="2">
            <Text color="gray" className="font-bold text-base">
              {CATEGORY_LABELS[category]}
            </Text>
            <Box className="overflow-hidden rounded-(--radius-2) border border-(--gray-5)">
              {category === "general" &&
                leadingGeneralShortcuts.map((shortcut) => (
                  <Flex
                    key={shortcut.id}
                    align="center"
                    justify="between"
                    px="3"
                    className="group border-b border-b-(--gray-4) pt-[6px] pb-[6px] last:border-b-0 odd:bg-(--gray-2) even:bg-(--gray-1)"
                  >
                    <Text className="text-sm">{shortcut.description}</Text>
                    <Flex gap="2" align="center">
                      <ShortcutKeys keys={shortcut.keys} />
                      {shortcut.onEdit && (
                        <button
                          type="button"
                          aria-label={`Change ${shortcut.description}`}
                          title={`Change ${shortcut.description}`}
                          onClick={shortcut.onEdit}
                          className="text-(--gray-9) opacity-0 transition-opacity hover:text-(--gray-12) focus-visible:opacity-100 group-hover:opacity-100"
                        >
                          <PencilSimple size={14} />
                        </button>
                      )}
                    </Flex>
                  </Flex>
                ))}
              {uniqueShortcuts.map((shortcut) => (
                <Flex
                  key={shortcut.id}
                  align="center"
                  justify="between"
                  px="3"
                  className="border-b border-b-(--gray-4) pt-[6px] pb-[6px] last:border-b-0 odd:bg-(--gray-2) even:bg-(--gray-1)"
                >
                  <Text className="text-sm">{shortcut.description}</Text>
                  <ShortcutKeys
                    keys={shortcut.keys}
                    alternateKeys={shortcut.alternateKeys}
                  />
                </Flex>
              ))}
            </Box>
          </Flex>
        );
      })}
    </Flex>
  );
}

function SingleShortcutKeys({ keys }: { keys: string }) {
  const parts = formatHotkeyParts(keys);

  return (
    <Flex gap="1" align="center">
      {parts.map((part) => (
        <Keycap key={part} label={part} />
      ))}
    </Flex>
  );
}

function ShortcutKeys({
  keys,
  alternateKeys,
}: {
  keys: string;
  alternateKeys?: string;
}) {
  if (!alternateKeys) {
    return <SingleShortcutKeys keys={keys} />;
  }

  return (
    <Flex gap="1" align="center">
      <SingleShortcutKeys keys={keys} />
      <Text color="gray" className="text-[13px]">
        or
      </Text>
      <SingleShortcutKeys keys={alternateKeys} />
    </Flex>
  );
}
