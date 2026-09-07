import { Info } from "@phosphor-icons/react";
import {
  isImageBuildFailed,
  isImageBuildInProgress,
} from "@posthog/shared/domain-types";
import { imageFailureDetail } from "@posthog/ui/features/settings/sections/environments/imageBuildWatcher";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { Button, Flex, IconButton, Text } from "@radix-ui/themes";

export function ImageBuilderBuildButton({ taskId }: { taskId: string }) {
  const { images, buildMutation } = useSandboxCustomImages();
  const image = images.find((img) => img.builder_task_id === taskId);
  if (!image) return null;

  const inProgress = isImageBuildInProgress(image.status);
  const isFailed = isImageBuildFailed(image.status);

  return (
    <Flex align="center" gap="2" className="shrink-0">
      {inProgress ? (
        <Text color="gray" className="text-[12px]">
          {image.status === "scanning" ? "scanning…" : "building…"}
        </Text>
      ) : image.status === "ready" ? (
        <Text color="green" className="text-[12px]">
          ready · v{image.version}
        </Text>
      ) : isFailed ? (
        <Flex align="center" gap="1">
          <Text color="red" className="text-[12px]">
            {image.status === "scan_failed" ? "scan failed" : "build failed"}
          </Text>
          <Tooltip
            side="top"
            align="end"
            content={
              <div className="max-w-80 whitespace-pre-wrap">
                <Text className="font-medium text-xs">Failure reason</Text>
                <Text as="div" color="gray" className="mt-1 text-xs">
                  {imageFailureDetail(image)}
                </Text>
              </div>
            }
          >
            <IconButton
              size="1"
              variant="ghost"
              color="red"
              aria-label="Show image build failure reason"
            >
              <Info size={14} />
            </IconButton>
          </Tooltip>
        </Flex>
      ) : null}
      <Button
        size="1"
        variant="soft"
        onClick={() => buildMutation.mutate({ id: image.id })}
        loading={buildMutation.isPending}
        disabled={inProgress || buildMutation.isPending}
      >
        Save & build
      </Button>
    </Flex>
  );
}
