import { Text } from "@components/text";
import { useRouter } from "expo-router";
import { MagnifyingGlass, Plus, PuzzlePiece } from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  TextInput,
  View,
} from "react-native";
import { FloatingMcpHeader } from "@/features/mcp/components/FloatingMcpHeader";
import {
  installationToRowProps,
  McpServerRow,
  recommendedToRowProps,
} from "@/features/mcp/components/McpServerRow";
import { useMcpInstallations, useMcpMarketplace } from "@/features/mcp/hooks";
import type {
  McpRecommendedServer,
  McpServerInstallation,
} from "@/features/mcp/types";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";

type Tab = "installed" | "marketplace";

export default function McpServersScreen() {
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("installed");
  const [search, setSearch] = useState("");

  const installations = useMcpInstallations();
  const marketplace = useMcpMarketplace();

  const installedNames = useMemo(
    () => new Set((installations.data ?? []).map((i) => i.name)),
    [installations.data],
  );

  const handleAddCustom = () => router.push("/mcp-servers/add-custom");

  const handleOpenInstallation = (i: McpServerInstallation) =>
    router.push({
      pathname: "/mcp-servers/installation/[id]",
      params: { id: i.id },
    });

  const handleOpenTemplate = (t: McpRecommendedServer) =>
    router.push({
      pathname: "/mcp-servers/template/[id]",
      params: { id: t.id },
    });

  const filteredInstallations = useMemo(() => {
    const list = installations.data ?? [];
    if (!search) return list;
    const q = search.toLowerCase();
    return list.filter(
      (i) =>
        (i.display_name ?? i.name).toLowerCase().includes(q) ||
        i.url?.toLowerCase().includes(q),
    );
  }, [installations.data, search]);

  const filteredMarketplace = useMemo(() => {
    const list = marketplace.data ?? [];
    if (!search) return list;
    const q = search.toLowerCase();
    return list.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.description?.toLowerCase().includes(q),
    );
  }, [marketplace.data, search]);

  const isPending =
    tab === "installed" ? installations.isPending : marketplace.isPending;

  return (
    <View className="flex-1 bg-background">
      <FloatingMcpHeader title="MCP servers" onAddPress={handleAddCustom} />

      <View className="flex-1" style={{ paddingTop: insets.top + 60 }}>
        {/* Tab bar */}
        <View className="mb-2 flex-row gap-2 px-4">
          {(["installed", "marketplace"] as const).map((t) => {
            const active = tab === t;
            return (
              <Pressable
                key={t}
                onPress={() => setTab(t)}
                className={`flex-1 items-center rounded-lg border px-3 py-2 ${active ? "border-accent-9 bg-accent-3" : "border-gray-5 bg-card active:bg-gray-2"}`}
              >
                <Text
                  className={`font-medium text-[14px] ${active ? "text-accent-11" : "text-gray-11"}`}
                >
                  {t === "installed" ? "Installed" : "Marketplace"}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {/* Search */}
        <View className="mb-3 px-4">
          <View className="flex-row items-center gap-2 rounded-lg border border-gray-5 bg-card px-3 py-2">
            <MagnifyingGlass size={16} color={themeColors.gray[10]} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder={
                tab === "installed" ? "Filter installed" : "Search marketplace"
              }
              placeholderTextColor={themeColors.gray[10]}
              className="flex-1 text-[14px] text-gray-12"
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>
        </View>

        {isPending ? (
          <View className="flex-1 items-center justify-center">
            <ActivityIndicator color={themeColors.accent[9]} />
          </View>
        ) : tab === "installed" ? (
          <FlatList
            data={filteredInstallations}
            keyExtractor={(i) => i.id}
            renderItem={({ item }) => (
              <McpServerRow
                {...installationToRowProps(item, handleOpenInstallation)}
              />
            )}
            ListEmptyComponent={
              <InstalledEmpty
                onBrowsePress={() => setTab("marketplace")}
                onAddCustom={handleAddCustom}
              />
            }
            refreshControl={
              <RefreshControl
                refreshing={installations.isRefetching}
                onRefresh={() => installations.refetch()}
                tintColor={themeColors.accent[9]}
              />
            }
            contentContainerStyle={{ paddingBottom: bottom("default") }}
          />
        ) : (
          <FlatList
            data={filteredMarketplace}
            keyExtractor={(t) => t.id}
            renderItem={({ item }) => (
              <McpServerRow
                {...recommendedToRowProps(
                  item,
                  installedNames,
                  handleOpenTemplate,
                )}
              />
            )}
            ListEmptyComponent={<MarketplaceEmpty />}
            refreshControl={
              <RefreshControl
                refreshing={marketplace.isRefetching}
                onRefresh={() => marketplace.refetch()}
                tintColor={themeColors.accent[9]}
              />
            }
            contentContainerStyle={{ paddingBottom: bottom("default") }}
          />
        )}
      </View>
    </View>
  );
}

function InstalledEmpty({
  onBrowsePress,
  onAddCustom,
}: {
  onBrowsePress: () => void;
  onAddCustom: () => void;
}) {
  const themeColors = useThemeColors();
  return (
    <View className="items-center px-8 py-16">
      <View className="mb-4 h-12 w-12 items-center justify-center rounded-full bg-gray-3">
        <PuzzlePiece size={22} color={themeColors.gray[11]} weight="bold" />
      </View>
      <Text className="mb-1 font-semibold text-[16px] text-gray-12">
        No MCP servers installed
      </Text>
      <Text className="mb-5 text-center text-[13px] text-gray-10 leading-snug">
        MCP servers extend your agent with extra tools. Browse the marketplace
        or add a custom URL to get started.
      </Text>
      <View className="flex-row gap-2">
        <Pressable
          onPress={onBrowsePress}
          className="rounded-lg bg-accent-9 px-4 py-2 active:opacity-80"
        >
          <Text className="font-semibold text-[14px] text-accent-contrast">
            Browse marketplace
          </Text>
        </Pressable>
        <Pressable
          onPress={onAddCustom}
          className="flex-row items-center gap-1 rounded-lg border border-gray-5 bg-card px-3 py-2 active:bg-gray-2"
        >
          <Plus size={14} color={themeColors.gray[12]} weight="bold" />
          <Text className="font-medium text-[14px] text-gray-12">
            Add custom
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

function MarketplaceEmpty() {
  return (
    <View className="items-center px-8 py-16">
      <Text className="text-center text-[13px] text-gray-10">
        No servers match your search.
      </Text>
    </View>
  );
}
