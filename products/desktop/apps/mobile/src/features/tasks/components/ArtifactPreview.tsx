import type { TaskRunArtifact } from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";
import { ArrowSquareOut, Warning, X } from "phosphor-react-native";
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import WebView from "react-native-webview";
import { MarkdownText } from "@/features/chat";
import { applyCspToHtml } from "@/features/mcp/sandbox/mcpAppCsp";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";
import { useCloudAttachmentPreview } from "../hooks/useCloudAttachmentPreview";
import { artifactPreviewKind } from "../utils/artifactPreview";

interface ArtifactPreviewProps {
  taskId: string;
  runId: string;
  artifact: TaskRunArtifact;
  onClose: () => void;
}

export function ArtifactPreview({
  taskId,
  runId,
  artifact,
  onClose,
}: ArtifactPreviewProps) {
  const insets = useSafeAreaInsets();
  const themeColors = useThemeColors();
  const name = artifact.name ?? "artifact";
  const kind = artifactPreviewKind(name);

  const { data: url, isLoading: urlLoading } = useCloudAttachmentPreview(
    taskId,
    artifact.id ? { runId, artifactId: artifact.id } : undefined,
  );

  // Markdown and HTML render from the file's text; images and the external
  // fallback only need the presigned URL.
  const needsText = kind === "markdown" || kind === "html";
  const {
    data: text,
    isLoading: textLoading,
    isError: textError,
  } = useQuery({
    queryKey: ["artifactText", url],
    enabled: needsText && Boolean(url),
    staleTime: Infinity,
    retry: false,
    queryFn: async (): Promise<string> => {
      const response = await fetch(url ?? "");
      if (!response.ok) throw new Error("Artifact fetch failed");
      return response.text();
    },
  });

  const loading = urlLoading || (needsText && textLoading);

  return (
    <Modal
      visible
      animationType="slide"
      presentationStyle="fullScreen"
      onRequestClose={onClose}
    >
      <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
        <View className="flex-row items-center gap-3 px-4 pb-2">
          <Text
            className="flex-1 font-semibold text-[16px] text-gray-12"
            numberOfLines={1}
          >
            {name}
          </Text>
          {url ? (
            <Pressable
              onPress={() => openExternalUrl(url)}
              hitSlop={8}
              className="active:opacity-60"
              accessibilityLabel="Open externally"
            >
              <ArrowSquareOut size={20} color={themeColors.gray[12]} />
            </Pressable>
          ) : null}
          <Pressable
            onPress={onClose}
            hitSlop={8}
            className="active:opacity-60"
            accessibilityLabel="Close preview"
          >
            <X size={20} color={themeColors.gray[12]} />
          </Pressable>
        </View>

        <View className="flex-1" style={{ paddingBottom: insets.bottom }}>
          {loading ? (
            <View className="flex-1 items-center justify-center">
              <ActivityIndicator color={themeColors.accent[9]} />
            </View>
          ) : !url || textError || kind === "unsupported" ? (
            <Unsupported
              url={url}
              onShare={() => url && openExternalUrl(url)}
            />
          ) : kind === "image" ? (
            <Image
              source={{ uri: url }}
              resizeMode="contain"
              style={{ flex: 1, width: "100%" }}
            />
          ) : kind === "markdown" ? (
            <ScrollView
              className="flex-1"
              contentContainerStyle={{ padding: 16 }}
            >
              <MarkdownText content={text ?? ""} disableRemoteImages />
            </ScrollView>
          ) : (
            <WebView
              originWhitelist={["*"]}
              source={{ html: applyCspToHtml(text ?? "") }}
              // Untrusted agent output: no scripts, and the sandbox never
              // navigates to a remote page. Only a genuine tap ("click") opens
              // externally — automatic redirects (e.g. a <meta http-equiv=
              // "refresh">) are dropped so previewing a file can't silently
              // launch an attacker URL. The injected CSP blocks remote resource
              // loads on top of that.
              javaScriptEnabled={false}
              setSupportMultipleWindows={false}
              onShouldStartLoadWithRequest={(req) => {
                if (
                  req.url.startsWith("http://") ||
                  req.url.startsWith("https://")
                ) {
                  if (req.navigationType === "click") openExternalUrl(req.url);
                  return false;
                }
                return true;
              }}
              style={{ flex: 1, backgroundColor: "#fff" }}
            />
          )}
        </View>
      </View>
    </Modal>
  );
}

function Unsupported({
  url,
  onShare,
}: {
  url: string | null | undefined;
  onShare: () => void;
}) {
  const themeColors = useThemeColors();
  return (
    <View className="flex-1 items-center justify-center gap-4 px-8">
      <Warning size={28} color={themeColors.gray[9]} />
      <Text className="text-center text-[14px] text-gray-11">
        This file can't be previewed here.
      </Text>
      {url ? (
        <Pressable
          onPress={onShare}
          className="flex-row items-center gap-2 rounded-lg bg-gray-3 px-4 py-2.5 active:opacity-70"
        >
          <ArrowSquareOut size={16} color={themeColors.gray[12]} />
          <Text className="text-[14px] text-gray-12">Open externally</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
