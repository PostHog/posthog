import { Plugs } from "@phosphor-icons/react";
import { iconDomainFromServerUrl } from "@posthog/core/mcp-servers/iconDomain";
import { useServerIcon } from "@posthog/ui/features/mcp-servers/hooks/useServerIcon";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { Flex } from "@radix-ui/themes";
import { useState } from "react";

interface ServerIconProps {
  /** The template's brand domain (`icon_domain`). Falls back to deriving one from serverUrl. */
  iconDomain?: string | null;
  /** The MCP server URL — lets custom installs without a template still get a brand icon. */
  serverUrl?: string | null;
  size?: number;
  className?: string;
}

/**
 * Brand logo for an MCP server, resolved at render time through the
 * authenticated logo.dev icon proxy (`mcp_servers/icon/`). Falls back to a
 * generic plug glyph when no brand domain resolves or the proxy has no icon.
 */
export function ServerIcon({
  iconDomain,
  serverUrl,
  size = 32,
  className,
}: ServerIconProps) {
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const domain = iconDomain || iconDomainFromServerUrl(serverUrl);
  // logo.dev picks the logo variant suited to the active background theme.
  const theme = isDarkMode ? "dark" : "light";
  const src = useServerIcon(domain, theme);
  // Failure latches per (domain, theme) — the unit the icon varies over — so
  // a bad payload in one theme doesn't blank the other and a theme flip retries.
  const iconKey = `${domain}|${theme}`;
  const [failedIconKey, setFailedIconKey] = useState<string | null>(null);
  const dimension = `${size}px`;
  const radius = 2;
  return (
    <Flex
      align="center"
      justify="center"
      className={`shrink-0 overflow-hidden ${className ?? ""}`}
      style={{ width: dimension, height: dimension, borderRadius: radius }}
    >
      {src && failedIconKey !== iconKey ? (
        <img
          src={src}
          alt=""
          className="size-full object-contain"
          style={{ borderRadius: radius }}
          onError={() => setFailedIconKey(iconKey)}
        />
      ) : (
        <Plugs size={Math.round(size * 0.55)} className="text-gray-11" />
      )}
    </Flex>
  );
}
