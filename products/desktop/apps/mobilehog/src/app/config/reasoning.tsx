import { getReasoningEffortOptions } from "@posthog/shared";
import { useRouter } from "expo-router";
import { ScrollView, View } from "react-native";
import { SheetHeader } from "@/components/SheetHeader";
import { SheetRow, sheetStyles } from "@/components/SheetRow";
import { useComposer } from "@/lib/composer";

export default function ReasoningPage() {
  const router = useRouter();
  const { adapter, model, reasoning, setReasoning } = useComposer();
  const options = getReasoningEffortOptions(adapter, model) ?? [];

  return (
    <ScrollView
      style={sheetStyles.root}
      contentContainerStyle={sheetStyles.list}
    >
      <SheetHeader title="Reasoning" back />
      <View style={sheetStyles.card}>
        {options.map((option, index) => (
          <SheetRow
            key={option.value}
            first={index === 0}
            radio={option.value === reasoning}
            label={option.name}
            onPress={() => {
              setReasoning(option.value);
              router.back();
            }}
          />
        ))}
      </View>
    </ScrollView>
  );
}
