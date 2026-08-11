import { Alert } from "react-native";
import { SelectSheet } from "@/features/tasks/composer/SelectSheet";
import { useProjectsQuery } from "../hooks/useProjectsQuery";
import { useAuthStore } from "../stores/authStore";

interface ProjectSelectSheetProps {
  open: boolean;
  title?: string;
  onClose: () => void;
}

/**
 * Project picker over the token's scoped teams — the one place that owns the
 * option shape, the `Project N` name fallback, and the out-of-scope alert.
 * Selecting switches the active project via the auth store (which drops
 * project-scoped query caches); the rejection alert is defensive, since the
 * options are the scoped teams themselves.
 */
export function ProjectSelectSheet({
  open,
  title = "Active project",
  onClose,
}: ProjectSelectSheetProps) {
  const { projectId, scopedTeams, setProjectId } = useAuthStore();
  const { data: projects } = useProjectsQuery();

  return (
    <SelectSheet
      open={open}
      title={title}
      value={projectId != null ? String(projectId) : ""}
      onChange={(value) => {
        if (!setProjectId(Number(value))) {
          Alert.alert(
            "Can't switch project",
            "Your login isn't authorized for that project. Log out and back in to grant access to it.",
          );
        }
      }}
      onClose={onClose}
      options={scopedTeams.map((id) => ({
        value: String(id),
        label: projects?.find((p) => p.id === id)?.name || `Project ${id}`,
        description: String(id),
      }))}
    />
  );
}
