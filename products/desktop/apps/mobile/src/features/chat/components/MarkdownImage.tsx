import { ImageBroken } from "phosphor-react-native";
import { useEffect, useState } from "react";
import { ActivityIndicator, Image, Pressable, Text, View } from "react-native";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";

interface MarkdownImageProps {
  url: string;
  alt?: string;
}

type LoadState =
  | { status: "loading" }
  | { status: "loaded"; aspectRatio: number }
  | { status: "error" };

const MAX_HEIGHT = 320;

export function MarkdownImage({ url, alt }: MarkdownImageProps) {
  const themeColors = useThemeColors();
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    Image.getSize(
      url,
      (width, height) => {
        if (cancelled) return;
        const aspectRatio = height > 0 ? width / height : 1;
        setState({ status: "loaded", aspectRatio });
      },
      () => {
        if (cancelled) return;
        setState({ status: "error" });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (state.status === "error") {
    return (
      <View className="flex-row items-center gap-2 rounded-md border border-gray-6 bg-gray-2 px-3 py-2">
        <ImageBroken size={16} color={themeColors.gray[9]} />
        <Text className="flex-1 text-[12px] text-gray-10" numberOfLines={1}>
          {alt || "Failed to load image"}
        </Text>
      </View>
    );
  }

  if (state.status === "loading") {
    return (
      <View className="h-32 items-center justify-center rounded-md border border-gray-6 bg-gray-2">
        <ActivityIndicator size="small" color={themeColors.gray[9]} />
      </View>
    );
  }

  return (
    <Pressable
      onPress={() => openExternalUrl(url)}
      accessibilityRole="image"
      accessibilityLabel={alt || "Image"}
      className="active:opacity-80"
    >
      <Image
        source={{ uri: url }}
        resizeMode="contain"
        style={{
          width: "100%",
          aspectRatio: state.aspectRatio,
          maxHeight: MAX_HEIGHT,
          borderRadius: 6,
        }}
      />
      {alt ? (
        <Text className="mt-1 text-[11px] text-gray-9 italic" numberOfLines={2}>
          {alt}
        </Text>
      ) : null}
    </Pressable>
  );
}
