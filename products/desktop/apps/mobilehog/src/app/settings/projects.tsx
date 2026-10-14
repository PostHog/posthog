import { useRouter } from "expo-router";
import { ActivityIndicator, Alert, ScrollView, Text, View } from "react-native";
import { SheetHeader } from "@/components/SheetHeader";
import { SheetRow, sheetStyles } from "@/components/SheetRow";
import { useAuth } from "@/lib/auth";
import { useProjects } from "@/lib/projects";
import { colors } from "@/lib/theme";

export default function ProjectsPage() {
  const router = useRouter();
  const projects = useProjects();
  const currentId = useAuth((s) => s.session?.projectId);
  const selectProject = useAuth((s) => s.selectProject);

  return (
    <ScrollView
      style={sheetStyles.root}
      contentContainerStyle={sheetStyles.list}
    >
      <SheetHeader title="Projects" back />
      {projects.isLoading ? (
        <ActivityIndicator color={colors.inkSoft} style={{ marginTop: 24 }} />
      ) : null}
      {projects.isError ? (
        <Text style={sheetStyles.footnote}>
          Could not load projects. Go back and try again.
        </Text>
      ) : null}
      {projects.data?.length ? (
        <View style={sheetStyles.card}>
          {projects.data.map((project, index) => (
            <SheetRow
              key={project.id}
              first={index === 0}
              checked={project.id === currentId}
              label={project.name}
              onPress={async () => {
                try {
                  await selectProject(project.id, project.name);
                  router.back();
                } catch {
                  Alert.alert(
                    "Could not switch project",
                    "Check your connection and try again.",
                  );
                }
              }}
            />
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}
