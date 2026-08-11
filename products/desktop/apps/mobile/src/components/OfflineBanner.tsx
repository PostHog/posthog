import { WifiSlash } from "phosphor-react-native";
import { Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export const OFFLINE_BANNER_HEIGHT = 36;

interface OfflineBannerProps {
  isConnected: boolean;
}

export function OfflineBanner({ isConnected }: OfflineBannerProps) {
  const insets = useSafeAreaInsets();

  if (isConnected) return null;

  return (
    <View
      className="absolute inset-x-0 z-50 flex-row items-center justify-center gap-2 bg-status-error px-4 py-2"
      style={{ top: insets.top, minHeight: OFFLINE_BANNER_HEIGHT }}
    >
      <WifiSlash size={16} color="#fff" weight="bold" />
      <Text className="font-medium text-sm text-white">
        No internet connection
      </Text>
    </View>
  );
}
