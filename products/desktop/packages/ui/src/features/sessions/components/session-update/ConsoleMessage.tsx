import { Box, Text } from "@radix-ui/themes";

interface ConsoleMessageProps {
  level: "info" | "debug" | "warn" | "error";
  message: string;
  timestamp?: string;
}

export function ConsoleMessage({ level, message }: ConsoleMessageProps) {
  const getLevelColor = () => {
    switch (level) {
      case "error":
        return "text-red-11";
      case "warn":
        return "text-yellow-11";
      case "debug":
        return "text-purple-11";
      default:
        return "text-gray-10";
    }
  };

  return (
    <Box className="border-gray-4 border-l-2 py-0.5 pl-3">
      <Text className="text-[13px] text-gray-11">
        <Text className={getLevelColor()}>[{level}]</Text> {message}
      </Text>
    </Box>
  );
}
