import { applyCspToHtml } from "@posthog/core/mcp-apps/csp";
import type { TaskRunArtifact } from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowSquareOut,
  ArrowsClockwise,
  Stop,
  Warning,
  X,
} from "phosphor-react-native";
import { useMemo, useState } from "react";
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
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";
import { useCloudAttachmentPreview } from "../hooks/useCloudAttachmentPreview";
import {
  denyMediaCapture,
  removeAutomaticRedirects,
} from "../utils/artifactHtml";
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
  const [stopped, setStopped] = useState(false);

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
  const htmlControlsVisible =
    kind === "html" && !!url && !textError && !loading;
  const previewControl = stopped
    ? {
        label: "Restart preview",
        Icon: ArrowsClockwise,
        onPress: () => setStopped(false),
      }
    : { label: "Stop preview", Icon: Stop, onPress: () => setStopped(true) };
  const html = useMemo(
    () =>
      applyCspToHtml(denyMediaCapture(removeAutomaticRedirects(text ?? ""))),
    [text],
  );

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
          {htmlControlsVisible ? (
            <Pressable
              onPress={previewControl.onPress}
              hitSlop={8}
              className="active:opacity-60"
              accessibilityLabel={previewControl.label}
            >
              <previewControl.Icon size={20} color={themeColors.gray[12]} />
            </Pressable>
          ) : null}
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
          ) : stopped ? (
            <PreviewStopped />
          ) : (
            // Untrusted agent scripts run in the WebView's isolated web-content
            // process; keep it sealed. Do not add onMessage or injectedJavaScript
            // (a bridge back into the app). The rest of the props deny file and
            // device access, and the CSP applied above denies the network.
            // Two props below are iOS-only, and Android is covered elsewhere:
            // onFileDownload (Android keeps the library's own DownloadListener,
            // so downloads there are suppressed by the navigation gate rejecting
            // the http(s) request first) and mediaCapturePermissionGrantType
            // (denyMediaCapture strips the getUserMedia entry points out of the
            // document instead).
            <WebView
              originWhitelist={["*"]}
              source={{ html }}
              javaScriptEnabled
              setSupportMultipleWindows={false}
              allowFileAccess={false}
              allowFileAccessFromFileURLs={false}
              allowUniversalAccessFromFileURLs={false}
              geolocationEnabled={false}
              mediaPlaybackRequiresUserAction
              mediaCapturePermissionGrantType="deny"
              onFileDownload={() => {}}
              onShouldStartLoadWithRequest={(req) => {
                // Allowlist, so the boundary fails closed: with scripts enabled
                // an artifact can set location.href to any scheme without a
                // gesture, and tel:/sms:/mailto:/deep links hand off to another
                // app. source={{ html }} loads against the about:blank base URL,
                // which is the only navigation allowed to happen in place.
                if (req.url === "about:blank") return true;
                // A link activation leaves the preview and opens in the system
                // browser instead; everything else is dropped.
                if (
                  req.navigationType === "click" &&
                  (req.url.startsWith("http://") ||
                    req.url.startsWith("https://"))
                ) {
                  openExternalUrl(req.url);
                }
                return false;
              }}
              style={{ flex: 1, backgroundColor: "#fff" }}
            />
          )}
        </View>
      </View>
    </Modal>
  );
}

function PreviewStopped() {
  return (
    <View className="flex-1 items-center justify-center px-8">
      <Text className="text-center text-[14px] text-gray-11">
        Preview stopped. Restart it to run the HTML again.
      </Text>
    </View>
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
