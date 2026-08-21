import type { EvidencePreview } from "@posthog/api-client/evidence-previews";
import { Card, CardContent, Text } from "@posthog/quill";
import { EvidenceSparkline } from "@posthog/ui/features/editor/components/EvidenceRefChip";

export function PostHogObjectDetails({
  preview,
}: {
  preview: EvidencePreview;
}) {
  const sections = preview.sections ?? [];
  const showActivity = preview.spark && preview.spark.points.length > 1;

  if (!showActivity && sections.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {showActivity && preview.spark && (
        <Card size="sm">
          <CardContent className="p-3">
            <Text size="xs" weight="medium" variant="muted">
              Activity
            </Text>
            <EvidenceSparkline
              points={preview.spark.points}
              render={preview.spark.render}
            />
          </CardContent>
        </Card>
      )}
      {sections.map((section) => (
        <Card key={section.title} size="sm">
          <CardContent className="p-3">
            <Text size="sm" weight="semibold">
              {section.title}
            </Text>
            <dl className="mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2">
              {section.fields.map((field) => (
                <div key={field.label} className="min-w-0">
                  <dt className="text-muted-foreground text-xs">
                    {field.label}
                  </dt>
                  <dd className="mt-0.5 break-words text-sm">{field.value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
