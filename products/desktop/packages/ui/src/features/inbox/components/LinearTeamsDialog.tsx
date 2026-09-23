import type {
  LinearTeam,
  SignalSourceConfig,
} from "@posthog/api-client/posthog-client";
import {
  buildLinearTeamIdsConfig,
  linearTeamIdsFromConfig,
} from "@posthog/core/integrations/linearSourceTeams";
import {
  Button,
  Checkbox,
  CheckboxIndicator,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  RadioGroup,
  RadioGroupItem,
  ScrollArea,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  type LinearTeamsStatus,
  useLinearTeams,
} from "@posthog/ui/features/inbox/hooks/useLinearTeams";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

type Scope = "all" | "selected";

interface LinearTeamsDialogProps {
  /** The Linear source row, or null before the source was ever turned on. */
  config: SignalSourceConfig | null;
  /** Saving from the enable flow turns the source on; saving from the card leaves it as it is. */
  enableOnSave: boolean;
  viaSetupWizard: boolean;
  open: boolean;
  onClose: () => void;
}

function LinearTeamList({
  teams,
  status,
  selected,
  onToggle,
  disabled,
}: {
  teams: LinearTeam[];
  status: LinearTeamsStatus;
  selected: string[];
  onToggle: (id: string, checked: boolean) => void;
  disabled: boolean;
}) {
  if (status === "loading") {
    return (
      <div className="flex items-center gap-2 py-2">
        <Spinner aria-hidden="true" />
        <Text size="sm" variant="muted">
          Loading teams…
        </Text>
      </div>
    );
  }
  if (status !== "ready") {
    return (
      <Text size="sm" className="text-warning">
        PostHog can't reach your Linear connection, so the team list isn't
        available. Reconnect Linear in integration settings, then try again.
      </Text>
    );
  }
  if (teams.length === 0) {
    return (
      <Text size="sm" variant="muted">
        This Linear workspace has no teams to pick from.
      </Text>
    );
  }
  return (
    <ScrollArea className="max-h-56">
      <div className="flex flex-col gap-1 pr-2">
        {teams.map((team) => {
          const checked = selected.includes(team.id);
          return (
            <Label
              key={team.id}
              className="flex items-center gap-2 rounded-(--radius-2) px-1 py-1"
            >
              <Checkbox
                checked={checked}
                onCheckedChange={(next) => onToggle(team.id, next === true)}
                disabled={disabled}
              >
                <CheckboxIndicator checked={checked} />
              </Checkbox>
              <span className="min-w-0 truncate text-sm">{team.name}</span>
            </Label>
          );
        })}
      </div>
    </ScrollArea>
  );
}

/**
 * Choose which Linear teams Self-driving reads before the source goes on, and change that
 * scope afterwards. The warehouse still syncs the whole workspace; the scope decides which
 * issues become signals, so it applies from the next sync.
 */
export function LinearTeamsDialog({
  config,
  enableOnSave,
  viaSetupWizard,
  open,
  onClose,
}: LinearTeamsDialogProps) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const savedTeamIds = linearTeamIdsFromConfig(config?.config);
  const [scope, setScope] = useState<Scope>(
    savedTeamIds.length > 0 ? "selected" : "all",
  );
  const [teamIds, setTeamIds] = useState<string[]>(savedTeamIds);
  const { teams, status } = useLinearTeams(open);

  const save = useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Not authenticated");
      if (projectId == null) throw new Error("No project selected");
      const nextIds = scope === "all" ? [] : teamIds;
      if (config) {
        await client.updateSignalSourceConfig(projectId, config.id, {
          enabled: enableOnSave ? true : config.enabled,
          config: buildLinearTeamIdsConfig(config.config, nextIds),
        });
      } else {
        await client.createSignalSourceConfig(projectId, {
          source_product: "linear",
          source_type: "issue",
          enabled: true,
          config: buildLinearTeamIdsConfig(null, nextIds),
        });
      }
      return nextIds.length;
    },
    onSuccess: (teamCount) => {
      if (enableOnSave) {
        track(ANALYTICS_EVENTS.SIGNAL_SOURCE_CONNECTED, {
          source_product: "linear",
          is_first_connection: !config,
          via_setup_wizard: viaSetupWizard,
        });
      }
      toast.success(
        teamCount === 0
          ? "Linear reads all teams from the next sync."
          : `Linear reads ${teamCount} ${teamCount === 1 ? "team" : "teams"} from the next sync.`,
      );
      void queryClient.invalidateQueries({
        queryKey: ["signals", "source-configs"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["inbox", "signal-reports"],
      });
      onClose();
    },
    onError: (saveError) => {
      toast.error(
        saveError instanceof Error
          ? saveError.message
          : "Failed to save the Linear teams",
      );
    },
  });

  const toggleTeam = (id: string, checked: boolean) => {
    setTeamIds((prev) =>
      checked ? [...prev, id] : prev.filter((teamId) => teamId !== id),
    );
  };

  const nothingPicked = scope === "selected" && teamIds.length === 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !save.isPending) onClose();
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Linear teams</DialogTitle>
          <DialogDescription>
            Choose which Linear teams Self-driving reads. It reads open issues
            only from those teams.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3">
            <RadioGroup
              value={scope}
              onValueChange={(next) => setScope(next as Scope)}
              aria-label="Which Linear teams to read"
            >
              <Label className="flex items-center gap-2">
                <RadioGroupItem value="all" disabled={save.isPending} />
                <span className="text-sm">All teams</span>
              </Label>
              <Label className="flex items-center gap-2">
                <RadioGroupItem value="selected" disabled={save.isPending} />
                <span className="text-sm">Only the teams I pick</span>
              </Label>
            </RadioGroup>
            {scope === "selected" ? (
              <div className="flex flex-col gap-1">
                <LinearTeamList
                  teams={teams}
                  status={status}
                  selected={teamIds}
                  onToggle={toggleTeam}
                  disabled={save.isPending}
                />
                <Text size="xs" variant="muted">
                  Applies from the next sync. Reports already in your inbox
                  stay.
                </Text>
                {nothingPicked ? (
                  <Text size="xs" className="text-warning">
                    Pick at least one team, or read all teams.
                  </Text>
                ) : null}
              </div>
            ) : null}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={save.isPending || nothingPicked}
          >
            {enableOnSave && !config?.enabled ? "Turn on Linear" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
