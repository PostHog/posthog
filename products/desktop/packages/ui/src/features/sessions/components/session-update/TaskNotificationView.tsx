import { CheckCircle, StopCircle, XCircle } from "@phosphor-icons/react";
import { Box, Flex, Text } from "@radix-ui/themes";

interface TaskNotificationViewProps {
  status: "completed" | "failed" | "stopped";
  summary: string;
}

const statusConfig = {
  completed: {
    icon: <CheckCircle size={14} weight="fill" className="text-green-9" />,
    label: "Task completed",
    borderColor: "border-green-6 dark:border-green-8",
  },
  failed: {
    icon: <XCircle size={14} weight="fill" className="text-red-9" />,
    label: "Task failed",
    borderColor: "border-red-6 dark:border-red-8",
  },
  stopped: {
    icon: <StopCircle size={14} weight="fill" className="text-orange-9" />,
    label: "Task stopped",
    borderColor: "border-orange-6 dark:border-orange-8",
  },
};

export function TaskNotificationView({
  status,
  summary,
}: TaskNotificationViewProps) {
  const config = statusConfig[status];

  return (
    <Box className={`my-1 border-l-2 py-1 pl-3 ${config.borderColor}`}>
      <Flex direction="column" gap="1">
        <Flex align="center" gap="2">
          {config.icon}
          <Text className="font-medium text-[13px] text-gray-12">
            {config.label}
          </Text>
        </Flex>
        {summary && <Text className="text-[13px] text-gray-11">{summary}</Text>}
      </Flex>
    </Box>
  );
}
