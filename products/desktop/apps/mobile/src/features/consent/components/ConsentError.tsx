import { Text } from "@components/text";
import { Pressable, View } from "react-native";

interface ConsentErrorProps {
  onRetry: () => void;
}

export function ConsentError({ onRetry }: ConsentErrorProps) {
  return (
    <View className="gap-4">
      <Text className="font-semibold text-2xl text-gray-12">
        Couldn't check organization consent
      </Text>
      <Text className="text-base text-gray-11">
        Check your connection and try again. If it keeps happening, contact
        support.
      </Text>
      <Pressable
        className="mt-1 items-center rounded-lg bg-accent-9 py-3 active:opacity-80"
        onPress={onRetry}
      >
        <Text className="font-semibold text-accent-contrast text-sm">
          Retry
        </Text>
      </Pressable>
    </View>
  );
}
