import { modelCostInfo } from "@posthog/core/billing/modelPricing";
import { buildProviderModelGroups } from "@posthog/shared";
import { useRouter } from "expo-router";
import { useMemo } from "react";
import { ScrollView, Text, View } from "react-native";
import { SheetHeader } from "@/components/SheetHeader";
import { SheetRow, sheetStyles } from "@/components/SheetRow";
import { useComposer } from "@/lib/composer";
import { useModels } from "@/lib/queries";

export default function ModelPage() {
  const router = useRouter();
  const models = useModels();
  const model = useComposer((s) => s.model);
  const adapter = useComposer((s) => s.adapter);
  const setModel = useComposer((s) => s.setModel);
  const groups = useMemo(
    () => buildProviderModelGroups(models.data ?? [], adapter, model),
    [models.data, adapter, model],
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
      <Text style={sheetStyles.footnote}>
        × is cost per token vs Claude Sonnet 5
      </Text>
    </ScrollView>
  );
}
