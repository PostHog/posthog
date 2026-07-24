import {
  ArrowLeft,
  ArrowRight,
  ArrowSquareOut,
  ArrowsClockwise,
  Check,
  Copy,
  GitBranch,
  GithubLogo,
  Play,
  Warning,
} from "@phosphor-icons/react";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { EXTERNAL_LINKS } from "@posthog/shared";
import {
  ANALYTICS_EVENTS,
  type OnboardingStepCompletedProperties,
} from "@posthog/shared/analytics-events";
import { builderHog } from "@posthog/ui/assets/hedgehogs";
import {
  CliCheckPanel,
  InstalledBadge,
} from "@posthog/ui/features/onboarding/components/CliCheckPanel";
import { OptionalBadge } from "@posthog/ui/features/onboarding/components/OptionalBadge";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import { Terminal } from "@posthog/ui/features/terminal/Terminal";
import { terminalManager } from "@posthog/ui/features/terminal/TerminalManager";
import { OnboardingHogTip } from "@posthog/ui/primitives/OnboardingHogTip";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { isMac } from "@posthog/ui/utils/platform";
import { Box, Button, Flex, IconButton, Text } from "@radix-ui/themes";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";

function CommandLine({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [command]);

  return (
    <Flex
      align="center"
      justify="between"
      gap="2"
      className="rounded-(--radius-2) border border-(--gray-a3) bg-(--gray-2) py-[6px] pr-2 pl-3"
    >
      <Flex align="center" gap="2" className="min-w-0">
        <Text className="select-none font-[var(--code-font-family)] text-(--gray-9) text-sm">
          $
        </Text>
        <Text className="truncate font-[var(--code-font-family)] text-(--gray-12) text-sm">
          {command}
        </Text>
      </Flex>
      <Tooltip content={copied ? "Copied!" : "Copy command"}>
        <IconButton
          size="1"
          variant="ghost"
          color="gray"
          onClick={() => void handleCopy()}
          aria-label="Copy command"
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
        </IconButton>
      </Tooltip>
    </Flex>
  );
}

/**
 * A command the user can copy, or — on macOS — run directly in an embedded
 * terminal. The run streams into an interactive xterm (so flows like
 * `gh auth login` that prompt or open a browser work), and on a clean exit
 * calls `onSuccess` so the parent can re-check install/auth status.
 */
function RunnableCommand({
  displayCommand,
  runCommand,
  sessionPrefix,
  analyticsCommand,
  onSuccess,
}: {
  displayCommand: string;
  runCommand?: string;
  sessionPrefix: string;
  analyticsCommand: "install_git" | "install_gh" | "auth_gh";
  onSuccess?: () => void;
}) {
  const hostClient = useHostTRPCClient();
  const [copied, setCopied] = useState(false);
  // 0 = not started; each run bumps the generation for a fresh PTY/session.
  const [generation, setGeneration] = useState(0);
  const [exitCode, setExitCode] = useState<number | null>(null);

  const sessionId = `${sessionPrefix}-${generation}`;
  const isRunning = generation > 0 && exitCode === null;

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(displayCommand);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [displayCommand]);

  const handleRun = useCallback(() => {
    setExitCode(null);
    setGeneration((g) => g + 1);
  }, []);

  const handleExit = useCallback(
    (code?: number) => {
      const resolved = code ?? 0;
      setExitCode(resolved);
      track(ANALYTICS_EVENTS.ONBOARDING_CLI_RUN_COMPLETED, {
        command: analyticsCommand,
        exit_code: resolved,
      });
      if (resolved === 0) {
        void onSuccess?.();
      }
    },
    [analyticsCommand, onSuccess],
  );

  // Tear down the embedded terminal (and its PTY, if still alive) when the user
  // re-runs or this command unmounts — onboarding shells shouldn't outlive it.
  useEffect(() => {
    if (generation === 0) return;
    return () => {
      terminalManager.destroy(sessionId);
      void hostClient.shell.destroy.mutate({ sessionId }).catch(() => {});
    };
  }, [sessionId, generation, hostClient]);

  return (
    <Flex direction="column" gap="2">
      <Flex
        align="center"
        justify="between"
        gap="2"
        className="rounded-(--radius-2) border border-(--gray-a3) bg-(--gray-2) py-[6px] pr-2 pl-3"
      >
        <Flex align="center" gap="2" className="min-w-0">
          <Text className="select-none font-[var(--code-font-family)] text-(--gray-9) text-sm">
            $
          </Text>
          <Text className="truncate font-[var(--code-font-family)] text-(--gray-12) text-sm">
            {displayCommand}
          </Text>
        </Flex>
        <Flex align="center" gap="2" className="shrink-0">
          {isMac && (
            <Button size="1" onClick={handleRun} loading={isRunning}>
              <Play size={14} weight="fill" />
              Run
            </Button>
          )}
          <Tooltip content={copied ? "Copied!" : "Copy command"}>
            <IconButton
              size="1"
              variant="ghost"
              color="gray"
              onClick={() => void handleCopy()}
              aria-label="Copy command"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </IconButton>
          </Tooltip>
        </Flex>
      </Flex>

      {generation > 0 && (
        <Box className="h-[220px] overflow-hidden rounded-(--radius-2) border border-(--gray-a3) bg-(--gray-2)">
          <Terminal
            key={sessionId}
            sessionId={sessionId}
            persistenceKey={sessionId}
            cwd="~"
            command={runCommand ?? displayCommand}
            onExit={handleExit}
          />
        </Box>
      )}

      {exitCode !== null && exitCode !== 0 && (
        <Text className="text-(--amber-11) text-xs">
          Exited with code {exitCode}. Re-run it, or copy the command to run
          manually.
        </Text>
      )}
    </Flex>
  );
}

type StepContext = Pick<
  OnboardingStepCompletedProperties,
  "git_installed" | "gh_installed" | "gh_authenticated"
>;

interface InstallCliStepProps {
  onNext: (context?: StepContext) => void;
  onBack: () => void;
}

export function InstallCliStep({ onNext, onBack }: InstallCliStepProps) {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  const [isCheckingGit, setIsCheckingGit] = useState(false);
  const [isCheckingGh, setIsCheckingGh] = useState(false);
  const { data: gitStatus, isLoading: isLoadingGit } = useQuery(
    trpc.git.getGitStatus.queryOptions(undefined, { staleTime: 30_000 }),
  );
  const { data: ghStatus, isLoading: isLoadingGh } = useQuery(
    trpc.git.getGhStatus.queryOptions(undefined, { staleTime: 30_000 }),
  );
  const gitInstalled = gitStatus?.installed ?? false;
  const ghInstalled = ghStatus?.installed ?? false;
  const ghAuthenticated = ghStatus?.authenticated ?? false;

  const checkFiredRef = useRef(false);
  useEffect(() => {
    if (checkFiredRef.current) return;
    if (gitStatus === undefined || ghStatus === undefined) return;
    checkFiredRef.current = true;
    track(ANALYTICS_EVENTS.ONBOARDING_CLI_CHECK_COMPLETED, {
      git_installed: gitInstalled,
      gh_installed: ghInstalled,
      gh_authenticated: ghAuthenticated,
    });
  }, [gitStatus, ghStatus, gitInstalled, ghInstalled, ghAuthenticated]);

  const handleCheckGit = useCallback(async () => {
    setIsCheckingGit(true);
    await queryClient.invalidateQueries(trpc.git.getGitStatus.pathFilter());
    setIsCheckingGit(false);
  }, [queryClient, trpc]);

  const handleCheckGh = useCallback(async () => {
    setIsCheckingGh(true);
    await queryClient.invalidateQueries(trpc.git.getGhStatus.pathFilter());
    setIsCheckingGh(false);
  }, [queryClient, trpc]);

  const handleContinue = () => {
    onNext({
      git_installed: gitInstalled,
      gh_installed: ghInstalled,
      gh_authenticated: ghAuthenticated,
    });
  };

  return (
    <Flex align="center" height="100%" px="8">
      <Flex
        direction="column"
        align="center"
        className="h-full w-full pt-[24px] pb-[40px]"
      >
        <Flex direction="column" className="min-h-0 flex-1 overflow-y-auto">
          <Flex
            direction="column"
            gap="5"
            className="m-auto w-full max-w-[560px]"
          >
            <Flex direction="column" gap="5" className="w-full">
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                <Flex direction="column" gap="2">
                  <Flex align="center" gap="2">
                    <Text className="font-bold text-(--gray-12) text-2xl">
                      Install CLI tools
                    </Text>
                    <OptionalBadge />
                  </Flex>
                  <Text className="text-(--gray-11) text-sm">
                    Agents use these to manage branches and open pull requests
                    on your behalf.
                  </Text>
                </Flex>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.05 }}
              >
                <CliCheckPanel
                  icon={<GitBranch size={18} className="text-(--gray-12)" />}
                  title="Git"
                  isLoading={isLoadingGit}
                  statusBadge={
                    gitInstalled ? (
                      <InstalledBadge
                        label={`Installed${gitStatus?.version ? ` (${gitStatus.version})` : ""}`}
                      />
                    ) : null
                  }
                >
                  {!isLoadingGit && !gitInstalled && (
                    <Flex direction="column" gap="3">
                      <Text className="text-(--gray-11) text-sm">
                        Install with Homebrew or Xcode Command Line Tools:
                      </Text>
                      <Flex direction="column" gap="2">
                        <RunnableCommand
                          displayCommand="brew install git"
                          sessionPrefix="onboarding-git-install"
                          analyticsCommand="install_git"
                          onSuccess={() => void handleCheckGit()}
                        />
                        <CommandLine command="xcode-select --install" />
                      </Flex>
                      <Flex align="center" justify="between" gap="3">
                        <Button
                          size="1"
                          variant="ghost"
                          color="gray"
                          onClick={() =>
                            openExternalUrl(EXTERNAL_LINKS.gitInstall)
                          }
                        >
                          Other install methods
                          <ArrowSquareOut size={12} />
                        </Button>
                        <Button
                          size="1"
                          variant="soft"
                          color="gray"
                          onClick={() => void handleCheckGit()}
                          loading={isCheckingGit}
                        >
                          <ArrowsClockwise size={12} />
                          Check again
                        </Button>
                      </Flex>
                    </Flex>
                  )}
                </CliCheckPanel>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.08 }}
              >
                <CliCheckPanel
                  icon={<GithubLogo size={18} className="text-(--gray-12)" />}
                  title="GitHub CLI"
                  isLoading={isLoadingGh}
                  statusBadge={
                    ghInstalled && ghAuthenticated ? (
                      <InstalledBadge
                        label={
                          ghStatus?.username
                            ? `Logged in as ${ghStatus.username}`
                            : "Authenticated"
                        }
                      />
                    ) : ghInstalled ? (
                      <Flex align="center" gap="1">
                        <Warning
                          size={14}
                          weight="fill"
                          className="text-(--amber-9)"
                        />
                        <Text className="text-(--amber-11) text-[13px]">
                          Not logged in
                        </Text>
                      </Flex>
                    ) : null
                  }
                >
                  {!isLoadingGh && !ghInstalled && (
                    <Flex direction="column" gap="3">
                      <Text className="text-(--gray-11) text-sm">
                        Install with Homebrew:
                      </Text>
                      <RunnableCommand
                        displayCommand="brew install gh"
                        sessionPrefix="onboarding-gh-install"
                        analyticsCommand="install_gh"
                        onSuccess={() => void handleCheckGh()}
                      />
                      <Flex align="center" justify="between" gap="3">
                        <Button
                          size="1"
                          variant="ghost"
                          color="gray"
                          onClick={() =>
                            openExternalUrl(EXTERNAL_LINKS.ghInstall)
                          }
                        >
                          Other install methods
                          <ArrowSquareOut size={12} />
                        </Button>
                        <Button
                          size="1"
                          variant="soft"
                          color="gray"
                          onClick={() => void handleCheckGh()}
                          loading={isCheckingGh}
                        >
                          <ArrowsClockwise size={12} />
                          Check again
                        </Button>
                      </Flex>
                    </Flex>
                  )}
                  {!isLoadingGh && ghInstalled && !ghAuthenticated && (
                    <Flex direction="column" gap="3">
                      <Text className="text-(--gray-11) text-sm">
                        Log in to the GitHub CLI
                      </Text>
                      <RunnableCommand
                        displayCommand="gh auth login"
                        runCommand="gh auth login --web --hostname github.com --git-protocol https"
                        sessionPrefix="onboarding-gh-auth"
                        analyticsCommand="auth_gh"
                        onSuccess={() => void handleCheckGh()}
                      />
                      <Flex justify="end">
                        <Button
                          size="1"
                          variant="soft"
                          color="gray"
                          onClick={() => void handleCheckGh()}
                          loading={isCheckingGh}
                        >
                          <ArrowsClockwise size={12} />
                          Check again
                        </Button>
                      </Flex>
                    </Flex>
                  )}
                </CliCheckPanel>
              </motion.div>
            </Flex>

            <OnboardingHogTip
              hogSrc={builderHog}
              message="No CLI? You can still continue and install these any time."
              delay={0.15}
            />
          </Flex>
        </Flex>

        <StepActions>
          <Button size="3" variant="outline" color="gray" onClick={onBack}>
            <ArrowLeft size={16} weight="bold" />
            Back
          </Button>
          <Button size="3" onClick={handleContinue}>
            Continue
            <ArrowRight size={16} weight="bold" />
          </Button>
        </StepActions>
      </Flex>
    </Flex>
  );
}
