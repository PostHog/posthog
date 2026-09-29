import { modelCostInfo } from "@posthog/core/billing/modelPricing";
import {
  adapterForModelId,
  buildProviderModelGroups,
  isTerminalStatus,
} from "@posthog/shared";
import { useRouter } from "expo-router";
import { useMemo } from "react";
import { ScrollView, Text, View } from "react-native";
import { SheetHeader } from "@/components/SheetHeader";
import { SheetRow, sheetStyles } from "@/components/SheetRow";
import { useComposer } from "@/lib/composer";
import { useModels, useTask } from "@/lib/queries";

export default function ModelPage() {
  const router = useRouter();
  const models = useModels();
  const contextId = useComposer((s) => s.contextId);
  const task = useTask(contextId === "new" ? "" : contextId);
  const run = task.data?.latest_run;
  const lockedAdapter =
    task.data?.runtime !== "pi" && run && !isTerminalStatus(run.status)
      ? run.runtime_adapter
      : null;
  const model = useComposer((s) => s.model);
  const adapter = useComposer((s) => s.adapter);
  const setModel = useComposer((s) => s.setModel);
  const groups = useMemo(
    () =>
      buildProviderModelGroups(
        (models.data ?? []).filter(
          (candidate) =>
            !lockedAdapter || adapterForModelId(candidate.id) === lockedAdapter,
        ),
        adapter,
        model,
      ),
    [models.data, adapter, model, lockedAdapter],
  );

  return (
    <ScrollView
      style={sheetStyles.root}
      contentContainerStyle={sheetStyles.list}
    >
      <SheetHeader title="Model" back />
      {groups.map((group) => (
        <View key={group.group} style={sheetStyles.section}>
          <Text style={sheetStyles.sectionTitle}>{group.name}</Text>
          <View style={sheetStyles.card}>
            {group.options.map((option, index) => (
              <SheetRow
                key={option.value}
                first={index === 0}
                radio={option.value === model}
                label={option.name}
                trailing={modelCostInfo(option.value)?.multiplierLabel}
                onPress={() => {
                  setModel(option.value);
                  router.back();
                }}
              />
            ))}
          </View>
        </View>
      ))}
      {lockedAdapter ? (
        <Text style={sheetStyles.footnote}>
          Stop the current run to choose a model from another provider.
        </Text>
      ) : null}
      <Text style={sheetStyles.footnote}>
        × is cost per token vs Claude Sonnet 5
      </Text>
    </ScrollView>
  );
}
