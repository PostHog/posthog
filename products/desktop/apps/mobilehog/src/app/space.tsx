import { useRouter } from "expo-router";
import { useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Glass } from "@/components/Glass";
import { SheetHeader } from "@/components/SheetHeader";
import { SheetRow, sheetStyles } from "@/components/SheetRow";
import { useSelectedSpace } from "@/lib/queries";
import { useSpace } from "@/lib/space";
import { colors, fonts, radius } from "@/lib/theme";

export default function SpaceSheet() {
  const router = useRouter();
  const spaces = useSelectedSpace();
  const setChannelId = useSpace((s) => s.setChannelId);
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const hasPersonal = spaces.data?.some(
    (space) => space.system_role === "personal",
  );
  const options = [...(spaces.data ?? [])]
    .filter((space) => space.name.toLowerCase().includes(needle))
    .sort(
      (a, b) =>
        Number(b.system_role === "personal") -
          Number(a.system_role === "personal") ||
        Number(b.starred) - Number(a.starred) ||
        a.name.localeCompare(b.name),
    );

  const choose = (id: string | null): void => {
    setChannelId(id);
    router.back();
  };

  return (
    <ScrollView
      style={sheetStyles.root}
      contentContainerStyle={sheetStyles.list}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="on-drag"
    >
      <SheetHeader title="Space" />
      <Glass style={styles.search}>
        <TextInput
          accessibilityLabel="Search spaces"
          value={query}
          onChangeText={setQuery}
          placeholder="Search spaces"
          placeholderTextColor={colors.inkMute}
          autoCapitalize="none"
          autoCorrect={false}
          clearButtonMode="while-editing"
          style={styles.input}
        />
      </Glass>
      {spaces.isLoading ? (
        <Text style={sheetStyles.footnote}>Loading spaces</Text>
      ) : null}
      {spaces.isError ? (
        <View style={styles.error}>
          <Text style={sheetStyles.footnote}>
            Could not load spaces. Try again.
          </Text>
          <Pressable
            accessibilityRole="button"
            disabled={spaces.isFetching}
            onPress={() => void spaces.refetch()}
          >
            <Text style={styles.retry}>
              {spaces.isFetching ? "Loading" : "Retry"}
            </Text>
          </Pressable>
        </View>
      ) : null}
      {spaces.isSuccess ? (
        <View style={sheetStyles.card}>
          {!spaces.data?.some((space) => space.system_role === "personal") &&
          !needle ? (
            <SheetRow
              first
              label="Personal"
              trailing="Private"
              radio={!spaces.selected && !spaces.unavailable}
              onPress={() => choose(null)}
            />
          ) : null}
          {options.map((space, index) => (
            <SheetRow
              key={space.id}
              first={index === 0 && (!!hasPersonal || !!needle)}
              label={space.name}
              trailing={space.channel_type === "public" ? undefined : "Private"}
              radio={spaces.selected?.id === space.id}
              onPress={() => choose(space.id)}
            />
          ))}
        </View>
      ) : null}
      {spaces.isSuccess && options.length === 0 ? (
        <Text style={sheetStyles.footnote}>
          {needle
            ? "No matching spaces. Try another search."
            : "Your first task will create your personal space."}
        </Text>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  search: {
    borderRadius: radius.pill,
    paddingHorizontal: 16,
    overflow: "hidden",
  },
  input: {
    fontFamily: fonts.sans,
    fontSize: 16,
    color: colors.ink,
    paddingVertical: 11,
  },
  error: { gap: 8 },
  retry: {
    fontFamily: fonts.sansSemi,
    fontSize: 15,
    color: colors.accent,
    padding: 8,
  },
});
