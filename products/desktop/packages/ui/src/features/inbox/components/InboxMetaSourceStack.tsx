import { InboxMetaText } from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { Flex, Tooltip } from "@radix-ui/themes";

interface InboxMetaSourceStackProps {
  /**
   * Distinct source products contributing signals to the report, in the order
   * the backend ships them (chronological). The first entry becomes the
   * primary label; the rest collapse into a hover-revealed `+ n` tail.
   */
  sourceProducts: string[] | null | undefined;
  /** Optional prefix prepended to the primary label, e.g. "Responder · ". */
  labelPrefix?: string;
}

/**
 * Renders one icon per distinct known source product, followed by the first
 * source product's label and a `+ n` tail when more sources contributed.
 * Hovering the `+ n` reveals the remaining source product names.
 */
export function InboxMetaSourceStack({
  sourceProducts,
  labelPrefix,
}: InboxMetaSourceStackProps) {
  const items = (sourceProducts ?? [])
    .map((key) => ({ key, meta: getSourceProductMeta(key) }))
    .filter(
      (
        entry,
      ): entry is {
        key: string;
        meta: NonNullable<ReturnType<typeof getSourceProductMeta>>;
      } => entry.meta !== null,
    );

  if (items.length === 0) return null;

  const primary = items[0];
  const overflow = items.slice(1);
  const overflowLabel = overflow.map((entry) => entry.meta.label).join(", ");

  return (
    <Flex align="center" gap="2" className="min-w-0">
      <Flex align="center" gap="1.5" className="shrink-0">
        {items.map((entry) => {
          const Icon = entry.meta.Icon;
          return (
            <span
              key={entry.key}
              className="inline-flex shrink-0 items-center text-current"
              style={{ color: entry.meta.color }}
              aria-hidden
            >
              <Icon size={12} className="block" />
            </span>
          );
        })}
      </Flex>
      <InboxMetaText>
        {labelPrefix}
        {primary.meta.label}
        {overflow.length > 0 ? (
          <>
            {" + "}
            <Tooltip content={overflowLabel}>
              <span className="cursor-help">{overflow.length}</span>
            </Tooltip>
          </>
        ) : null}
      </InboxMetaText>
    </Flex>
  );
}
