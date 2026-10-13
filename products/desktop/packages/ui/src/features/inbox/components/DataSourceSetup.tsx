import { GITHUB_INSTALL_PENDING_MESSAGE } from "@posthog/core/integrations/connectErrors";
import { githubIssuesSchemaNames } from "@posthog/core/integrations/githubSourceRepos";
import { Button } from "@posthog/quill";
import {
  EXTERNAL_INBOX_SOURCE_BY_PRODUCT,
  type ToggleableSourceProduct,
} from "@posthog/shared";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { GitHubRepoMultiPicker } from "@posthog/ui/features/folder-picker/GitHubRepoMultiPicker";
import { DynamicSourceSetup } from "@posthog/ui/features/inbox/components/DynamicSourceSetup";
import { GithubInstallRequestsBanner } from "@posthog/ui/features/integrations/components/GithubInstallRequestsBanner";
import {
  describeGithubConnectError,
  useGithubConnect,
} from "@posthog/ui/features/integrations/useGithubUserConnect";
import {
  useGithubRepositories,
  useRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { toast } from "@posthog/ui/primitives/toast";
import { Box, Flex, Text, TextField } from "@radix-ui/themes";
import { useCallback, useEffect, useState } from "react";

/** PostHog DWH: full table replication (non-incremental); API enum value `full_refresh`. */
const FULL_TABLE_REPLICATION = "full_refresh" as const;

function schemasPayload(tables: readonly string[]) {
  return tables.map((name) => ({
    name,
    should_sync: true,
    sync_type: FULL_TABLE_REPLICATION,
  }));
}

interface DataSourceSetupProps {
  source: ToggleableSourceProduct;
  onComplete: () => void;
  onCancel: () => void;
}

/**
 * Renders the connect flow for a warehouse inbox source. Credential-based sources
 * (`setup: "dynamic"`) render the generic `DynamicSourceSetup` form driven by the source's
 * connect-form schema served by PostHog Cloud — no per-source form code. The three legacy
 * special cases (GitHub repo picker, Zendesk, pganalyze) keep their bespoke forms.
 */
export function DataSourceSetup({
  source,
  onComplete,
  onCancel,
}: DataSourceSetupProps) {
  const config = EXTERNAL_INBOX_SOURCE_BY_PRODUCT[source];
  if (!config) return null;

  switch (config.setup) {
    case "github":
      return <GitHubSetup onComplete={onComplete} onCancel={onCancel} />;
    case "zendesk":
      return <ZendeskSetup onComplete={onComplete} onCancel={onCancel} />;
    case "pganalyze":
      return <PgAnalyzeSetup onComplete={onComplete} onCancel={onCancel} />;
    default:
      return (
        <DynamicSourceSetup
          sourceType={config.dwSourceType}
          title={`Connect ${config.label}`}
          schemas={schemasPayload(config.requiredTables)}
          onComplete={onComplete}
          onCancel={onCancel}
        />
      );
  }
}

interface SetupFormProps {
  onComplete: () => void;
  onCancel: () => void;
}

function GitHubSetup({ onComplete, onCancel }: SetupFormProps) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const client = useAuthenticatedClient();
  const {
    repositories,
    getIntegrationIdForRepo,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
    hasGithubIntegration,
  } = useRepositoryIntegration();
  const [repoPickerSearchQuery, setRepoPickerSearchQuery] = useState("");
  const [isRepoPickerOpen, setIsRepoPickerOpen] = useState(false);
  const {
    repositories: visibleRepositories,
    isPending: visibleRepositoriesLoading,
    isFetchingMore: visibleRepositoriesFetchingMore,
    hasMore: visibleRepositoriesHasMore,
    loadMore: loadMoreVisibleRepositories,
  } = useGithubRepositories(repoPickerSearchQuery, isRepoPickerOpen);
  const [repos, setRepos] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const {
    error: connectError,
    isConnecting: connecting,
    isTimedOut: timedOut,
    hasError: hasConnectError,
    isPending: awaitingApproval,
    connect: handleConnectGitHub,
  } = useGithubConnect({
    projectId,
    projectHasTeamIntegration: hasGithubIntegration,
  });
  // One warehouse source syncs through one installation, so every picked repo has to resolve to
  // the same team integration; the first repo decides which.
  const selectedIntegrationId = repos[0]
    ? getIntegrationIdForRepo(repos[0])
    : undefined;
  const mixedInstallations = repos.some(
    (repo) => getIntegrationIdForRepo(repo) !== selectedIntegrationId,
  );

  useEffect(() => {
    if (isLoadingRepos) return;
    const available = new Set(repositories);
    const known = repos.filter((repo) => available.has(repo));
    if (known.length !== repos.length) {
      setRepos(known);
    }
  }, [isLoadingRepos, repos, repositories]);

  const handleSubmit = useCallback(async () => {
    if (!projectId || !client || repos.length === 0 || !selectedIntegrationId) {
      return;
    }

    setLoading(true);
    try {
      await client.createExternalDataSource(projectId, {
        source_type: "Github",
        payload: {
          repositories: repos,
          auth_method: {
            selection: "oauth",
            github_integration_id: selectedIntegrationId,
          },
          // A multi-repo source names its schema rows per repository, so naming the bare
          // `issues` table here would leave every repository unsynced.
          schemas: schemasPayload(githubIssuesSchemaNames(repos)),
        },
      });
      toast.success("GitHub data source created");
      onComplete();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to create data source",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, client, onComplete, repos, selectedIntegrationId]);

  const handleRefreshRepositories = useCallback(() => {
    void refreshRepositories()
      .then(() => {
        toast.success("Repositories refreshed");
      })
      .catch((error) => {
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to refresh repositories",
        );
      });
  }, [refreshRepositories]);

  const handleRepoPickerOpenChange = useCallback((open: boolean) => {
    setIsRepoPickerOpen(open);
    if (!open) {
      setRepoPickerSearchQuery("");
    }
  }, []);

  const handleRepoPickerSearchChange = useCallback((value: string) => {
    setRepoPickerSearchQuery(value);
  }, []);

  if (!hasGithubIntegration) {
    const statusMessage = hasConnectError
      ? describeGithubConnectError(connectError)
      : awaitingApproval
        ? GITHUB_INSTALL_PENDING_MESSAGE
        : timedOut
          ? "We didn't hear back from GitHub. If the browser tab was closed, click Try again."
          : connecting
            ? "Waiting for GitHub… finish authorizing in your browser, then return here."
            : "Connect your GitHub account to import issues as Self-driving signals.";
    return (
      <SetupFormContainer title="Connect GitHub">
        <Flex direction="column" gap="3">
          <Text
            className={
              hasConnectError
                ? "text-(--red-11) text-sm"
                : "text-gray-11 text-sm"
            }
          >
            {statusMessage}
          </Text>
          {projectId != null ? (
            <GithubInstallRequestsBanner
              onFinishConnecting={() => void handleConnectGitHub()}
              isConnecting={connecting}
            />
          ) : null}
          <Flex gap="2" justify="end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onCancel}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => void handleConnectGitHub()}
              disabled={connecting}
            >
              {connecting
                ? "Waiting for authorization..."
                : hasConnectError || timedOut
                  ? "Try again"
                  : "Connect GitHub"}
            </Button>
          </Flex>
        </Flex>
      </SetupFormContainer>
    );
  }

  return (
    <SetupFormContainer title="Connect GitHub">
      <Flex direction="column" gap="3">
        <span className="text-gray-11 text-sm">
          Pick the repositories whose issues should feed Self-driving. You can
          add or remove repositories later.
        </span>
        <GitHubRepoMultiPicker
          value={repos}
          onChange={setRepos}
          repositories={isRepoPickerOpen ? visibleRepositories : repositories}
          isLoading={
            isLoadingRepos || (isRepoPickerOpen && visibleRepositoriesLoading)
          }
          isLoadingMore={visibleRepositoriesFetchingMore}
          hasMore={visibleRepositoriesHasMore}
          onLoadMore={loadMoreVisibleRepositories}
          open={isRepoPickerOpen}
          onOpenChange={handleRepoPickerOpenChange}
          searchQuery={repoPickerSearchQuery}
          onSearchQueryChange={handleRepoPickerSearchChange}
        />
        {mixedInstallations ? (
          <span className="text-(--amber-11) text-sm">
            Pick repositories from one GitHub installation per source.
          </span>
        ) : null}

        <Flex gap="2" justify="end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleRefreshRepositories}
            disabled={isRefreshingRepos}
          >
            {isRefreshingRepos ? "Refreshing…" : "Refresh repositories"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            disabled={
              repos.length === 0 ||
              !selectedIntegrationId ||
              mixedInstallations ||
              loading
            }
          >
            {loading ? "Creating..." : "Create source"}
          </Button>
        </Flex>
      </Flex>
    </SetupFormContainer>
  );
}

function ZendeskSetup({ onComplete, onCancel }: SetupFormProps) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const client = useAuthenticatedClient();
  const [subdomain, setSubdomain] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (!projectId || !client) return;
    if (!subdomain.trim() || !apiKey.trim() || !email.trim()) {
      toast.error("Please fill in all fields");
      return;
    }

    setLoading(true);
    try {
      await client.createExternalDataSource(projectId, {
        source_type: "Zendesk",
        payload: {
          subdomain: subdomain.trim(),
          api_key: apiKey.trim(),
          email_address: email.trim(),
          schemas: schemasPayload(["tickets"]),
        },
      });
      toast.success("Zendesk data source created");
      onComplete();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to create data source",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, client, subdomain, apiKey, email, onComplete]);

  const canSubmit = subdomain.trim() && apiKey.trim() && email.trim();

  return (
    <SetupFormContainer title="Connect Zendesk">
      <Flex direction="column" gap="3">
        <TextField.Root
          placeholder="Subdomain (e.g. mycompany)"
          value={subdomain}
          onChange={(e) => setSubdomain(e.target.value)}
        />
        <TextField.Root
          placeholder="API key"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        <TextField.Root
          placeholder="Email address"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <Flex gap="2" justify="end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            disabled={!canSubmit || loading}
          >
            {loading ? "Creating..." : "Create source"}
          </Button>
        </Flex>
      </Flex>
    </SetupFormContainer>
  );
}

function PgAnalyzeSetup({ onComplete, onCancel }: SetupFormProps) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const client = useAuthenticatedClient();
  const [apiKey, setApiKey] = useState("");
  const [organizationSlug, setOrganizationSlug] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (!projectId || !client) return;
    if (!apiKey.trim() || !organizationSlug.trim()) {
      toast.error("Please fill in all fields");
      return;
    }

    setLoading(true);
    try {
      await client.createExternalDataSource(projectId, {
        source_type: "PgAnalyze",
        payload: {
          api_key: apiKey.trim(),
          organization_slug: organizationSlug.trim(),
          schemas: schemasPayload(["issues", "servers"]),
        },
      });
      toast.success("pganalyze data source created");
      onComplete();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to create data source",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, client, apiKey, organizationSlug, onComplete]);

  const canSubmit = apiKey.trim() && organizationSlug.trim();

  return (
    <SetupFormContainer title="Connect pganalyze">
      <Flex direction="column" gap="3">
        <TextField.Root
          placeholder="Organization slug (e.g. my-company)"
          value={organizationSlug}
          onChange={(e) => setOrganizationSlug(e.target.value)}
        />
        <TextField.Root
          placeholder="API key"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />

        <Flex gap="2" justify="end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            disabled={!canSubmit || loading}
          >
            {loading ? "Creating..." : "Create source"}
          </Button>
        </Flex>
      </Flex>
    </SetupFormContainer>
  );
}

function SetupFormContainer({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Box
      p="4"
      className="rounded-(--radius-2) border border-border bg-(--color-panel-solid)"
    >
      <Flex direction="column" gap="3">
        <Flex align="center" justify="between">
          <Text className="font-medium text-gray-12 text-sm">{title}</Text>
        </Flex>
        {children}
      </Flex>
    </Box>
  );
}
