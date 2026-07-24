import { ClockIcon, LightningIcon, PlugsIcon } from "@phosphor-icons/react";
import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import {
  LOOP_TEMPLATE_CATEGORIES,
  LOOP_TEMPLATES,
  type LoopTemplate,
  type LoopTemplateCategory,
} from "../loopTemplates";

const TONE_CLASSES: Record<LoopTemplate["tone"], string> = {
  blue: "bg-(--blue-a3) text-(--blue-11)",
  red: "bg-(--red-a3) text-(--red-11)",
  purple: "bg-(--purple-a3) text-(--purple-11)",
  teal: "bg-(--teal-a3) text-(--teal-11)",
  amber: "bg-(--amber-a3) text-(--amber-11)",
  green: "bg-(--green-a3) text-(--green-11)",
};

/** The "start from a template" category picker and grid. `onSelect` seeds the create
 * wizard; the caller decides whether the new loop attaches to a context. */
export function LoopTemplatesSection({
  onSelect,
}: {
  onSelect: (template: LoopTemplate) => void;
}) {
  const [templateCategory, setTemplateCategory] =
    useState<LoopTemplateCategory>("engineering");

  return (
    <div className="@container flex flex-col gap-3">
      <div className="flex @min-[480px]:flex-row flex-col items-start @min-[480px]:items-center justify-between gap-3">
        <Text className="font-medium text-[12px] text-gray-10 uppercase tracking-wide">
          Start from a template
        </Text>
        <Flex className="gap-0.5 rounded-full border border-gray-5 bg-gray-2 p-0.5">
          {LOOP_TEMPLATE_CATEGORIES.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setTemplateCategory(option.value)}
              className={`rounded-full px-3 py-1 text-xs transition-colors ${
                templateCategory === option.value
                  ? "bg-(--gray-4) text-gray-12"
                  : "text-gray-10 hover:text-gray-12"
              }`}
            >
              {option.label}
            </button>
          ))}
        </Flex>
      </div>
      <div className="grid @min-[640px]:grid-cols-2 grid-cols-1 gap-3">
        {LOOP_TEMPLATES.filter(
          (template) => template.category === templateCategory,
        ).map((template) => (
          <div key={template.id} className="@container">
            <TemplateCard
              template={template}
              onSelect={() => onSelect(template)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function TemplateCard({
  template,
  onSelect,
}: {
  template: LoopTemplate;
  onSelect: () => void;
}) {
  const Icon = template.icon;
  const TriggerIcon = template.triggerLabel.startsWith("Triggered")
    ? LightningIcon
    : ClockIcon;
  return (
    <button
      type="button"
      onClick={onSelect}
      className="@container flex h-full w-full @min-[300px]:flex-row flex-col items-start gap-2.5 overflow-hidden rounded-(--radius-3) border border-border bg-(--color-panel-solid) p-3 text-left transition-colors hover:border-(--gray-6) hover:bg-(--gray-2)"
    >
      <Flex
        align="center"
        justify="center"
        className={`size-6 shrink-0 rounded-(--radius-2) ${TONE_CLASSES[template.tone]}`}
      >
        <Icon size={13} />
      </Flex>
      <Flex direction="column" gap="1" className="min-w-0 flex-1">
        <Text className="font-medium text-[13px] text-gray-12 leading-tight">
          {template.name}
        </Text>
        <Text className="text-[12px] text-gray-11 leading-snug">
          {template.description}
        </Text>
        <Flex
          align="start"
          gap="3"
          className="mt-0.5 w-full @min-[400px]:flex-row flex-col text-(--accent-11)"
        >
          <Flex align="center" className="min-w-0 gap-1.5">
            <TriggerIcon size={11} className="shrink-0" />
            <Text className="text-[11px]">{template.triggerLabel}</Text>
          </Flex>
          <Flex align="center" className="min-w-0 gap-1.5">
            <PlugsIcon size={11} className="shrink-0" />
            <Text className="min-w-0 text-[11px]">
              Works with {template.worksWith.join(" · ")}
            </Text>
          </Flex>
        </Flex>
      </Flex>
    </button>
  );
}
