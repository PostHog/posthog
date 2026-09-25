import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
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
import { useDefaultRepository, useRepositories } from "@/lib/queries";
import { useRepo } from "@/lib/repo";
import { colors, fonts, radius } from "@/lib/theme";

interface Option {
  key: string;
  label: string;
  detail?: string;
  value: string | null;
}

export default function RepositorySheet() {
  const router = useRouter();
  const repositories = useRepositories();
  const repository = useDefaultRepository();
  const setRepository = useRepo((s) => s.setRepository);
  const [query, setQuery] = useState("");

  const options = useMemo<Option[]>(() => {
    const needle = query.trim().toLowerCase();
    return [
      { key: "none", label: "No repository", value: null },
      ...(repositories.data ?? [])
        .filter((repo) => !needle || repo.toLowerCase().includes(needle))
        .map((repo) => ({
          key: repo,
          label: repo.split("/")[1] ?? repo,
          detail: repo.split("/")[0],
          value: repo,
        })),
    ];
  }, [repositories.data, query]);

  const selected = repository.data ?? null;
  const loading = repositories.isLoading;

  const choose = (option: Option): void => {
    setRepository(option.value);
    router.back();
  };

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.list}
      keyboardDismissMode="on-drag"
    >
      <SheetHeader title="Repository" />
      <Glass style={styles.search}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder="Search repositories"
          placeholderTextColor={colors.inkMute}
          autoCapitalize="none"
          autoCorrect={false}
          style={styles.searchInput}
        />
      </Glass>
      {loading && options.length <= 1 ? (
        <Text style={styles.empty}>Loading</Text>
      ) : null}
      <View style={styles.card}>
        {options.map((option, index) => {
          const active = option.value === selected;
          return (
            <Pressable
              key={option.key}
              onPress={() => choose(option)}
              style={({ pressed }) => [
                styles.row,
                index > 0 && styles.rowDivider,
                pressed && { opacity: 0.5 },
              ]}
            >
              <View style={{ flex: 1 }}>
                <Text style={[styles.label, active && styles.labelActive]}>
                  {option.label}
                </Text>
                {option.detail ? (
                  <Text style={styles.detail}>{option.detail}</Text>
                ) : null}
              </View>
              {active ? <Text style={styles.check}>✓</Text> : null}
            </Pressable>
          );
        })}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  search: {
    borderRadius: radius.pill,
    paddingHorizontal: 16,
    overflow: "hidden",
  },
  searchInput: {
    fontFamily: fonts.sans,
    fontSize: 16,
    color: colors.ink,
    paddingVertical: 11,
  },
  list: { padding: 18, paddingBottom: 40, gap: 12 },
  empty: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkMute,
    padding: 8,
  },
  card: {
    backgroundColor: "#FFFFFF",
    borderRadius: radius.card,
    paddingHorizontal: 16,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 13,
  },
  rowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  label: { fontFamily: fonts.sans, fontSize: 16, color: colors.ink },
  labelActive: { fontFamily: fonts.sansSemi },
  detail: {
    fontFamily: fonts.sans,
    fontSize: 13,
    color: colors.inkMute,
    marginTop: 1,
  },
  check: { fontFamily: fonts.sansBold, fontSize: 16, color: colors.accent },
});
