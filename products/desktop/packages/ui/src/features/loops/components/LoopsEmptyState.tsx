import { ArrowSquareOutIcon, PlusIcon } from "@phosphor-icons/react";
import { loopHog } from "@posthog/ui/assets/hedgehogs";
import { Button } from "@posthog/ui/primitives/Button";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { Flex, Text } from "@radix-ui/themes";

// Placeholder until the loops docs page lands; swap for the final URL.
const LOOPS_DOCS_URL = "https://posthog.com/docs/loops";

const GETTING_STARTED_STEPS = [
  "Describe what you want, or start from a template",
  "Pick when it runs and what it can touch",
  "Review it once, then it runs unattended in the cloud and reports back",
];

/** The illustrated getting-started card shown when there are no loops yet. `contextName`
 * tweaks the copy for a context's Loops tab. */
export function LoopsEmptyState({
  contextName,
  onCreate,
  disabledReason,
}: {
  contextName?: string;
  onCreate: () => void;
  disabledReason?: string | null;
}) {
  return (
    <div className="@container">
      <div className="flex @min-[720px]:flex-row flex-col items-center @min-[720px]:gap-0 gap-6 rounded-(--radius-3) border border-gray-6 border-dashed @min-[720px]:px-8 px-5 py-8">
        <Flex justify="center" className="@min-[720px]:w-2/5 w-full shrink-0">
          <img src={loopHog} alt="" className="h-auto w-52 object-contain" />
        </Flex>
        <Flex
          direction="column"
          align="start"
          gap="4"
          className="min-w-0 flex-1"
        >
          <Flex direction="column" gap="1">
            <Text className="font-semibold text-[16px] text-gray-12">
              {contextName
                ? `Create a loop for #${contextName}`
                : "Create your first loop"}
            </Text>
            <Text className="text-[13px] text-gray-11 leading-relaxed">
              Set it up once and it keeps running on its own, even with your
              laptop closed.
            </Text>
          </Flex>
          <div className="flex flex-col gap-2">
            {GETTING_STARTED_STEPS.map((step, index) => (
              <div key={step} className="flex items-center gap-2.5">
                <Flex
                  align="center"
                  justify="center"
                  className="size-5 shrink-0 rounded-full border border-(--gray-7) font-medium text-[11px] text-gray-11"
                >
                  {index + 1}
                </Flex>
                <Text className="text-[13px] text-gray-11">{step}</Text>
              </div>
            ))}
          </div>
          <Flex gap="2" wrap="wrap">
            <Button
              variant="solid"
              size="2"
              onClick={onCreate}
              disabled={disabledReason != null}
              disabledReason={disabledReason}
            >
              <PlusIcon size={14} />
              Create a loop
            </Button>
            <Button
              variant="outline"
              color="gray"
              size="2"
              onClick={() => void openUrlInBrowser(LOOPS_DOCS_URL)}
            >
              Learn more
              <ArrowSquareOutIcon size={14} />
            </Button>
          </Flex>
        </Flex>
      </div>
    </div>
  );
}
