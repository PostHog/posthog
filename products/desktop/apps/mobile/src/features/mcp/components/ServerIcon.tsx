import { useColorScheme } from "nativewind";
import { PuzzlePiece } from "phosphor-react-native";
import { useState } from "react";
import { Image, View } from "react-native";
import { useAuthStore } from "@/features/auth";
import { useThemeColors } from "@/lib/theme";
import { iconDomainFromServerUrl } from "../iconDomain";

interface ServerIconProps {
  /** The template's brand domain (`icon_domain`). Falls back to deriving one from serverUrl. */
  iconDomain?: string | null;
  /** The MCP server URL — lets custom installs without a template still get a brand icon. */
  serverUrl?: string | null;
  size?: number;
  className?: string;
}

/**
 * Renders the brand logo for an MCP server through the authenticated logo.dev
 * icon proxy (`mcp_servers/icon/`), keyed by the template's `icon_domain` with
 * a best-effort domain derived from the server URL as fallback. Falls back to
 * a generic plug glyph when no domain resolves or the proxy has no icon (404).
 */
export function ServerIcon({
  iconDomain,
  serverUrl,
  size = 32,
  className,
}: ServerIconProps) {
  const themeColors = useThemeColors();
  const { colorScheme } = useColorScheme();
  const oauthAccessToken = useAuthStore((state) => state.oauthAccessToken);
  const cloudRegion = useAuthStore((state) => state.cloudRegion);
  const projectId = useAuthStore((state) => state.projectId);
  const getCloudUrlFromRegion = useAuthStore(
    (state) => state.getCloudUrlFromRegion,
  );

  const domain = iconDomain || iconDomainFromServerUrl(serverUrl);
  // logo.dev picks the logo variant suited to the active background theme.
  const theme = colorScheme === "dark" ? "dark" : "light";
  // Failure latches per (domain, theme) — the unit the request URL varies
  // over — so a transient failure in one theme doesn't blank the other and a
  // theme flip retries.
  const iconCacheKey = `${domain}|${theme}`;
  const [failedIconKey, setFailedIconKey] = useState<string | null>(null);

  const iconUrl =
    domain &&
    oauthAccessToken &&
    cloudRegion &&
    projectId &&
    failedIconKey !== iconCacheKey
      ? `${getCloudUrlFromRegion(cloudRegion)}/api/environments/${projectId}/mcp_servers/icon/?domain=${encodeURIComponent(domain)}&theme=${theme}`
      : null;

  return (
    <View
      className={`shrink-0 items-center justify-center overflow-hidden rounded-md bg-card ${className ?? ""}`}
      style={{ width: size, height: size }}
    >
      {iconUrl ? (
        <Image
          source={{
            uri: iconUrl,
            headers: { Authorization: `Bearer ${oauthAccessToken}` },
          }}
          style={{ width: size, height: size }}
          resizeMode="contain"
          onError={() => setFailedIconKey(iconCacheKey)}
        />
      ) : (
        <PuzzlePiece
          size={Math.round(size * 0.55)}
          color={themeColors.gray[11]}
          weight="bold"
        />
      )}
    </View>
  );
}
