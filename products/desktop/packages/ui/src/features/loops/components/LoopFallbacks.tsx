import { Flex, Text } from "@radix-ui/themes";

export function LoopLoadError() {
  return (
    <Flex
      direction="column"
      align="center"
      gap="1"
      className="mx-auto mt-16 max-w-md rounded-(--radius-2) border border-(--gray-5) border-dashed px-6 py-10 text-center"
    >
      <Text className="font-medium text-[13px] text-gray-12">
        Couldn't load this loop
      </Text>
      <Text className="max-w-md text-[12px] text-gray-11 leading-snug">
        It may have been deleted, or the loops API returned an error.
      </Text>
    </Flex>
  );
}

export function LoopsEmptyNotice({
  title,
  hint,
}: {
  title: string;
  hint: string;
}) {
  return (
    <Flex
      align="center"
      justify="center"
      direction="column"
      gap="1"
      py="6"
      className="rounded border border-gray-6 border-dashed"
    >
      <Text className="font-medium text-sm">{title}</Text>
      <Text color="gray" className="max-w-[420px] text-center text-[13px]">
        {hint}
      </Text>
    </Flex>
  );
}

export function LoopsSkeleton() {
  return (
    <Flex direction="column" gap="2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[58px] animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)"
        />
      ))}
    </Flex>
  );
}
