import {
  formatGatewayModelName,
  getReasoningEffortOptions,
} from "@posthog/shared";
import { useRouter } from "expo-router";
import { ScrollView, View } from "react-native";
import { SheetHeader } from "@/components/SheetHeader";
import { SheetRow, sheetStyles } from "@/components/SheetRow";
import { useComposer } from "@/lib/composer";
import { useModels } from "@/lib/queries";

export default function RunOptionsMenu() {
  const router = useRouter();
  const config = useComposer();
  const models = useModels();
  const current = models.data?.find((model) => model.id === config.model);
  const efforts = getReasoningEffortOptions(config.adapter, config.model);
  const effortLabel =
    efforts?.find((option) => option.value === config.reasoning)?.name ?? "";

  return (
    <ScrollView
      style={sheetStyles.root}
      contentContainerStyle={sheetStyles.list}
    >
      <SheetHeader title="Run options" />
      <View style={sheetStyles.card}>
        <SheetRow
          first
          label="Model"
          value={current ? formatGatewayModelName(current) : config.model}
          onPress={() => router.push("/config/model")}
        />
        {efforts ? (
          <SheetRow
            label="Reasoning"
            value={effortLabel}
            onPress={() => router.push("/config/reasoning")}
          />
        ) : null}
      </View>
      <View style={sheetStyles.card}>
        <SheetRow
          first
          label="Reset to default"
          onPress={() => config.reset()}
        />
      </View>
    </ScrollView>
  );
}
