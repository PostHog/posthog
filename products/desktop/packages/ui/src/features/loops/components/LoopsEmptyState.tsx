import { loopHog } from "@posthog/ui/assets/hedgehogs";
import { Flex, Text } from "@radix-ui/themes";

const GETTING_STARTED_STEPS = [
  "Describe what you want, or start from a template",
  "Pick when it runs and what it can touch",
  "Review it once, then it runs unattended in the cloud and reports back",
];

/** The illustrated getting-started card shown when there are no loops yet. `contextName`
 * tweaks the copy for a context's Loops tab. */
export function LoopsEmptyState({ contextName }: { contextName?: string }) {
  return (
    <div className="@container">
      <div className="flex @min-[560px]:flex-row flex-col items-center @min-[560px]:gap-0 gap-6 rounded-(--radius-3) border border-gray-6 border-dashed @min-[560px]:px-8 px-5 py-8">
        <Flex justify="center" className="@min-[560px]:w-2/5 w-full shrink-0">
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
        </Flex>
      </div>
    </div>
  );
}
