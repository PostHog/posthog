// Analytics event types and properties

import type { Adapter } from "./adapter";
import type { SourceProduct } from "./inbox-types";

export interface PromptHistoryOpenedProperties {
  entry_count: number;
}

export interface PromptHistorySelectedProperties {
  entry_count: number;
  entry_age_seconds: number | null;
  had_pending_draft: boolean;
  had_search_query: boolean;
  prompt_length: number;
}

type ExecutionType = "cloud" | "local";
export type RepositoryProvider = "github" | "gitlab" | "local" | "none";
type TaskCreatedFrom = "cli" | "command-menu" | "sidebar-worktree";
type RepositorySelectSource = "task-creation" | "task-detail";
type GitActionType =
  | "push"
  | "pull"
  | "sync"
  | "publish"
  | "commit"
  | "commit-push"
  | "create-pr"
  | "view-pr"
  | "update-pr"
  | "branch-here";
export type FeedbackType = "good" | "bad" | "general";
type FileOpenSource = "sidebar" | "agent-suggestion" | "search" | "diff";
export type FileChangeType = "added" | "modified" | "deleted";
type StopReason = "user_cancelled" | "completed" | "error" | "timeout";
export type SkillButtonId =
  | "add-analytics"
  | "create-feature-flags"
  | "run-experiment"
  | "add-error-tracking"
  | "instrument-llm-calls"
  | "add-logging";
type SkillButtonSource = "primary" | "dropdown";
export type CommandMenuAction =
  | "home"
  | "new-task"
  | "settings"
  | "logout"
  | "toggle-theme"
  | "toggle-left-sidebar"
  | "open-review-panel"
  | "go-back"
  | "go-forward"
  | "open-task"
  | "open-channel"
  | "open-command-center"
  | "open-inbox"
  | "open-loops"
  | "open-usage"
  | "search-files"
  | "open-file"
  | "reload-window"
  | "show-log-folder"
  | "zoom-in"
  | "zoom-out"
  | "zoom-reset";

// Event property interfaces
export interface TaskListViewProperties {
  filter_type?: string;
  sort_field?: string;
  view_mode?: string;
}

export interface TaskCreateProperties {
  auto_run: boolean;
  created_from: TaskCreatedFrom;
  repository_provider?: RepositoryProvider;
  workspace_mode?: "local" | "worktree" | "cloud";
  has_branch?: boolean;
  /** Worktree mode: a project environment with a setup script was selected */
  has_environment_setup?: boolean;
  /** Cloud mode: a sandbox environment was selected */
  has_sandbox_environment?: boolean;
  cloud_run_source?: "manual" | "signal_report";
  cloud_pr_authorship_mode?: "user" | "bot";
  signal_report_id?: string;
  /** Worktree mode: repo has a non-empty .worktreelink file */
  uses_worktree_link?: boolean;
  /** Worktree mode: repo has a non-empty .worktreeinclude file */
  uses_worktree_include?: boolean;
  adapter?: Adapter;
}

export interface TaskViewProperties {
  task_id: string;
}

export interface TaskRunProperties {
  task_id: string;
  execution_type: ExecutionType;
}

export interface RepositorySelectProperties {
  repository_provider: RepositoryProvider;
  source: RepositorySelectSource;
}

export interface UserIdentifyProperties {
  email?: string;
  uuid?: string;
  project_id?: string;
  region?: string;
}
export interface TaskRunStartedProperties {
  task_id: string;
  execution_type: ExecutionType;
  model?: string;
  initial_mode?: string;
  adapter?: string;
}

export interface TaskRunCompletedProperties {
  task_id: string;
  execution_type: ExecutionType;
  duration_seconds: number;
  prompts_sent: number;
  stop_reason: StopReason;
}

export interface TaskRunCancelledProperties {
  task_id: string;
  execution_type: ExecutionType;
  duration_seconds: number;
  prompts_sent: number;
}

export interface TaskRunStoppedProperties {
  task_id: string;
  execution_type: ExecutionType;
  duration_seconds?: number;
  prompts_sent?: number;
}

export interface PromptSentProperties {
  task_id: string;
  is_initial: boolean;
  execution_type: ExecutionType;
  prompt_length_chars: number;
}

// Git operations
export interface GitActionExecutedProperties {
  action_type: GitActionType;
  success: boolean;
  task_id?: string;
  /** Number of staged files at time of action */
  staged_file_count?: number;
  /** Number of unstaged files at time of action */
  unstaged_file_count?: number;
  /** Whether user chose to commit all changes (vs staged only) */
  commit_all?: boolean;
  /** Whether stagedOnly mode was used for the commit */
  staged_only?: boolean;
}

export interface PrCreatedProperties {
  task_id?: string;
  success: boolean;
}

export interface AgentFileActivityProperties {
  task_id: string;
  branch_name: string | null;
}

// Branch link events. "auto" marks self-healing unlinks of branches that no
// longer exist anywhere (e.g. deleted after a PR merge).
type BranchLinkSource = "agent" | "user" | "auto" | "unknown";

export interface BranchLinkedProperties {
  task_id: string;
  branch_name: string;
  source: BranchLinkSource;
}

export interface BranchUnlinkedProperties {
  task_id: string;
  source: BranchLinkSource;
}

export interface BranchLinkDefaultBranchUnknownProperties {
  task_id: string;
  branch_name: string;
}

// File interactions
export interface FileOpenedProperties {
  file_extension: string;
  source: FileOpenSource;
  task_id?: string;
}

export interface FileDiffViewedProperties {
  file_extension: string;
  change_type: FileChangeType;
  task_id?: string;
}

export interface ReviewPanelViewedProperties {
  task_id: string;
}

export interface DiffViewModeChangedProperties {
  from_mode: "split" | "unified";
  to_mode: "split" | "unified";
}

// Workspace events
export interface WorkspaceCreatedProperties {
  task_id: string;
  mode: "cloud" | "worktree" | "local";
}

export interface WorkspaceScriptsStartedProperties {
  task_id: string;
  scripts_count: number;
}

export interface FolderRegisteredProperties {
  path_hash: string;
}

// Navigation events
export interface CommandMenuActionProperties {
  action_type: CommandMenuAction;
  /** Channel acted on for the bluebird `open-channel` / `open-task` actions. */
  channel_id?: string;
}

export type SidebarNavItem =
  | "new_task"
  | "search"
  | "inbox"
  | "agents"
  | "skills"
  | "mcp_servers"
  | "command_center"
  | "contexts"
  | "activity"
  | "configure"
  | "loops"
  | "more"
  | "customize_sidebar";

export interface SidebarNavItemClickedProperties {
  item: SidebarNavItem;
  /** True when the row was clicked inside the expanded More section. */
  in_more: boolean;
}

export interface SidebarCustomizedProperties {
  item: SidebarNavItem;
  /** True when the item was promoted to the top level, false when moved under More. */
  visible: boolean;
}

export interface SidebarReorderedProperties {
  item: SidebarNavItem;
  /** Zero-based position of the item in the nav after the drag. */
  to_index: number;
}

export interface BrainrotActivatedProperties {
  /** Grid layout preset, e.g. "2x2". */
  layout: string;
  /** Cells already holding a task when Brainrot was chosen. */
  filled_cells: number;
}

export interface SkillButtonTriggeredProperties {
  task_id: string;
  button_id: SkillButtonId;
  source: SkillButtonSource;
}

// Settings events
export interface SettingChangedProperties {
  setting_name: string;
  new_value: string | boolean | number;
  old_value?: string | boolean | number;
}

export interface CustomSoundAddedProperties {
  // How the clip was captured.
  source: "recording" | "import";
  // Whether the user applied the offered leading/trailing-silence trim.
  trimmed: boolean;
  // Length of the saved clip in ms (no clip contents or name — no PII).
  duration_ms: number;
}

// Error events
export interface TaskCreationFailedProperties {
  error_type: string;
  failed_step?: string;
}

export interface AgentSessionErrorProperties {
  task_id: string;
  error_type: string;
}

export interface CloudStreamDisconnectedProperties {
  task_id: string;
  run_id: string;
  team_id: number;
  error_title: string;
  retryable: boolean;
  reconnect_attempts: number;
  stream_error_attempts: number;
  cumulative_reconnect_attempts: number;
  was_bootstrapping: boolean;
}

// Permission events
export interface PermissionRespondedProperties {
  task_id: string;
  tool_name?: string;
  option_id?: string;
  option_kind?: string;
  custom_input?: string;
}

export interface PermissionCancelledProperties {
  task_id: string;
  tool_name?: string;
}

// Session config events
export interface SessionConfigChangedProperties {
  task_id: string;
  category: string;
  from_value: string;
  to_value: string;
}

// Tour events
type TourAction = "started" | "step_advanced" | "dismissed" | "completed";

export interface TourEventProperties {
  tour_id: string;
  action: TourAction;
  step_id?: string;
  step_index?: number;
  total_steps?: number;
}

// Branch mismatch events
type BranchMismatchAction = "switch" | "continue" | "cancel";

export interface BranchMismatchWarningShownProperties {
  task_id: string;
  linked_branch: string;
  current_branch: string;
  has_uncommitted_changes: boolean;
}

export interface BranchMismatchActionProperties {
  task_id: string;
  action: BranchMismatchAction;
  linked_branch: string;
  current_branch: string;
}

// Deep link events
export interface DeepLinkNewTaskProperties {
  has_prompt: boolean;
  has_repo: boolean;
  mode?: string;
  model?: string;
}

export interface DeepLinkPlanProperties {
  has_repo: boolean;
  mode?: string;
  model?: string;
  plan_length_chars: number;
}

export interface DeepLinkIssueProperties {
  owner: string;
  repo: string;
  issue_number: number;
  mode?: string;
  model?: string;
}

export interface DeepLinkIssueFailedProperties {
  owner: string;
  repo: string;
  issue_number: number;
  reason: "not_found" | "fetch_failed";
  error_message?: string;
}

export interface DeepLinkCanvasProperties {
  channel_id: string;
  dashboard_id: string;
}

export interface DeepLinkChannelProperties {
  channel_id: string;
  /** Present when the link targets a thread inside the channel. */
  task_id?: string;
}

// Feedback events
export interface TaskFeedbackProperties {
  task_id: string;
  task_run_id?: string;
  log_url?: string;
  event_count: number;
  feedback_type: FeedbackType;
  feedback_comment?: string;
}

// Onboarding events
export type OnboardingStepId =
  | "welcome"
  | "project-select"
  | "invite-code"
  | "connect-github"
  | "install-cli"
  | "import-config"
  | "select-repo";

type OnboardingSkipReason = "no_repo_selected" | "dev_skip";

export interface OnboardingStepViewedProperties {
  step_id: OnboardingStepId;
  step_index: number;
  total_steps: number;
}

export interface OnboardingStepCompletedProperties {
  step_id: OnboardingStepId;
  step_index: number;
  total_steps: number;
  duration_seconds: number;
  github_connected?: boolean;
  git_installed?: boolean;
  gh_installed?: boolean;
  gh_authenticated?: boolean;
}

export interface OnboardingStepSkippedProperties {
  step_id: OnboardingStepId;
  step_index: number;
  reason: OnboardingSkipReason;
}

export interface OnboardingSignInInitiatedProperties {
  region: string;
}

export interface OnboardingProjectSelectedProperties {
  had_multiple_orgs: boolean;
  had_multiple_projects: boolean;
}

export interface OnboardingInviteCodeSubmittedProperties {
  success: boolean;
  error_type?: string;
}

export interface OnboardingFolderSelectedProperties {
  has_git_remote: boolean;
  repository_provider: RepositoryProvider;
}

export interface OnboardingCliCheckCompletedProperties {
  git_installed: boolean;
  gh_installed: boolean;
  gh_authenticated: boolean;
}

export interface OnboardingCliRunCompletedProperties {
  command: "install_git" | "install_gh" | "auth_gh";
  exit_code: number;
}

export interface OnboardingCompletedProperties {
  duration_seconds: number;
  github_connected: boolean;
  repo_skipped: boolean;
}

export type OnboardingGithubConnectFlow =
  | "team_existing"
  | "team_alternative"
  | "user_new";

export interface OnboardingGithubConnectStartedProperties {
  flow_type: OnboardingGithubConnectFlow;
  is_retry: boolean;
}

export interface OnboardingGithubConnectFailedProperties {
  reason: "timeout" | "error";
  error_type?: string;
}

export interface OnboardingAbandonedProperties {
  last_step_id: OnboardingStepId;
  duration_seconds: number;
}

export interface AiConsentGateShownProperties {
  is_org_admin: boolean;
}

// Setup / onboarding events
type SetupDiscoveredTaskCategory =
  | "bug"
  | "security"
  | "dead_code"
  | "duplication"
  | "performance"
  | "stale_feature_flag"
  | "error_tracking"
  | "event_tracking"
  | "funnel"
  | "posthog_setup"
  | "experiment";

export interface SetupDiscoveryStartedProperties {
  discovery_task_id: string;
  discovery_task_run_id: string;
}

export interface SetupDiscoveryCompletedProperties {
  discovery_task_id: string;
  discovery_task_run_id: string;
  task_count: number;
  duration_seconds: number;
  signal_source: "structured_output" | "terminal_status" | "missing_output";
}

export interface SetupDiscoveryFailedProperties {
  discovery_task_id?: string;
  discovery_task_run_id?: string;
  reason: "failed" | "cancelled" | "timeout" | "startup_error";
  error_message?: string;
}

export interface SetupTaskSelectedProperties {
  discovered_task_id: string;
  category: SetupDiscoveredTaskCategory;
  position: number;
  total_discovered: number;
}

export interface SetupTaskDismissedProperties {
  discovered_task_id: string;
  category: SetupDiscoveredTaskCategory;
  position: number;
  total_discovered: number;
}

// Inbox events
export type InboxReportOpenMethod =
  | "click"
  | "click_cmd"
  | "click_shift"
  | "keyboard"
  | "deeplink"
  | "unknown";

export type InboxReportCloseMethod =
  | "next_report"
  | "deselected"
  | "navigated_away"
  | "unmount";

export type InboxReportActionType =
  | "dismiss"
  | "snooze"
  | "delete"
  | "reingest"
  | "create_pr"
  | "open_pr"
  | "copy_link"
  | "discuss"
  | "expand_signal"
  | "collapse_signal"
  | "expand_signal_section"
  | "view_signal_external"
  | "expand_why"
  | "click_suggested_reviewer"
  | "add_suggested_reviewer"
  | "remove_suggested_reviewer"
  | "expand_task_section"
  | "play_session_recording";

export type InboxReportActionSurface =
  | "detail_pane"
  | "toolbar"
  | "keyboard"
  | "list_row";

export interface InboxViewedProperties {
  report_count: number;
  total_count: number;
  ready_count: number;
  has_active_filters: boolean;
  source_product_filter: string[];
  status_filter_count: number;
  is_empty: boolean;
  /** Breakdown of the visible report_count by priority (P0–P4, or "unknown"). */
  priority_p0_count: number;
  priority_p1_count: number;
  priority_p2_count: number;
  priority_p3_count: number;
  priority_p4_count: number;
  priority_unknown_count: number;
  /** Breakdown of the visible report_count by actionability. */
  actionability_immediately_actionable_count: number;
  actionability_requires_human_input_count: number;
  actionability_not_actionable_count: number;
  actionability_unknown_count: number;
  /**
   * Tab badge counts shown in the v2 inbox header on load — the actual numbers
   * the user sees (Pull requests / Reports / Runs). Optional: only the desktop
   * v2 shell populates these; the mobile event omits them.
   */
  pulls_count?: number;
  reports_count?: number;
}

export interface InboxReportOpenedProperties {
  report_id: string;
  report_title: string | null;
  report_age_hours: number;
  status: string | null;
  priority: string | null;
  actionability: string | null;
  source_products: string[];
  rank: number;
  list_size: number;
  open_method: InboxReportOpenMethod;
  previous_report_id: string | null;
}

export interface InboxReportClosedProperties {
  report_id: string;
  report_title: string | null;
  report_age_hours: number;
  priority: string | null;
  actionability: string | null;
  time_spent_ms: number;
  scrolled: boolean;
  close_method: InboxReportCloseMethod;
}

export interface InboxReportScrolledProperties {
  report_id: string;
  report_title: string | null;
  report_age_hours: number;
  priority: string | null;
  actionability: string | null;
  rank: number;
  list_size: number;
  time_since_open_ms: number;
}

export interface UsageViewedProperties {
  is_pro: boolean;
  /** Monthly bucket percent (0-100), null when usage is unavailable. */
  sustained_used_percent: number | null;
  /** Daily bucket percent (0-100), null when usage is unavailable. */
  burst_used_percent: number | null;
}

export interface SpendAnalysisTaskOpenedProperties {
  /** Total LLM spend in USD across all products for the analysed window. */
  total_cost_usd: number;
  /** Desktop app spend in USD for the analysed window (subset of total). */
  scoped_cost_usd: number;
  /** Number of `$ai_generation` events in the analysed window. */
  scoped_event_count: number;
  /** Length of the analysed window in days. */
  window_days: number;
  /** Number of tool rows the receiving agent will see (capped at 10 in the prompt). */
  tool_row_count: number;
  /** Number of model rows the receiving agent will see. */
  model_row_count: number;
}

export interface InboxReportActionProperties {
  report_id: string;
  report_title: string | null;
  report_age_hours: number;
  priority: string | null;
  actionability: string | null;
  action_type: InboxReportActionType;
  surface: InboxReportActionSurface;
  is_bulk: boolean;
  bulk_size: number;
  rank: number;
  list_size: number;
  dismissal_reason?: string;
  dismissal_note?: string;
  signal_id?: string;
  signal_source_product?: string;
  signal_source_type?: string;
  signal_section?: "relevant_code" | "data_queried";
  why_field?: "priority" | "actionability";
  task_section?: "research" | "implementation";
  suggested_reviewer_login?: string;
  suggested_reviewer_uuid?: string;
  // True when the user submitted Discuss with a first question via the popover.
  has_question?: boolean;
  // The first question text the user typed before hitting Discuss. Truncated to
  // 500 chars to keep event payloads bounded.
  question_text?: string;
  // True when the user submitted Create PR with extra feedback via the popover.
  has_feedback?: boolean;
  // The feedback text the user typed before hitting Create PR. Truncated to
  // 500 chars to keep event payloads bounded.
  feedback_text?: string;
}

// Scout events
export type ScoutChatType =
  | "fleet_overview"
  | "recent_signals"
  | "scout_checkin"
  | "finding_discuss"
  | "author_scout";

export type ScoutSurface =
  | "fleet_list"
  | "scout_detail"
  | "empty_state"
  | "scout_findings";

export type ScoutActionType =
  | "expand_run"
  | "collapse_run"
  | "expand_emission"
  | "collapse_emission"
  | "open_task_run"
  | "open_skill_in_posthog"
  | "open_helper_skill"
  | "copy_finding_link"
  | "open_linked_report"
  | "show_more_emitted_runs"
  | "filter_runs"
  | "toggle_hide_disabled"
  | "filter_created_by"
  | "open_settings"
  | "close_settings"
  | "open_findings"
  | "filter_findings"
  | "sort_findings";

export interface ScoutFleetViewedProperties {
  scout_count: number;
  enabled_count: number;
  dry_run_count: number;
  custom_count: number;
  is_empty: boolean;
}

export interface ScoutDetailViewedProperties {
  skill_name: string;
  scout_origin: "canonical" | "custom";
  /** False when the runs window has data but no config exists for this scout. */
  has_config: boolean;
  enabled: boolean | null;
  /** Live (true) vs dry run (false); null when no config was found. */
  emit: boolean | null;
  run_interval_minutes: number | null;
  /** Run stats cover the fleet runs window (currently 24h). */
  run_count: number;
  emitted_signal_count: number;
  failed_run_count: number;
}

export interface ScoutConfigChangedProperties {
  skill_name: string;
  scout_origin: "canonical" | "custom";
  setting: "enabled" | "emit" | "run_interval_minutes";
  new_value: boolean | number;
  old_value: boolean | number;
  /** False when the server rejected the update and the change rolled back. */
  success: boolean;
}

export interface ScoutChatStartedProperties {
  chat_type: ScoutChatType;
  surface: ScoutSurface;
  /** Set for per-scout check-ins; absent for fleet-level questions. */
  skill_name?: string;
}

export interface ScoutActionProperties {
  action_type: ScoutActionType;
  surface: ScoutSurface;
  skill_name?: string;
  run_id?: string;
  run_status?: string;
  emitted_count?: number;
  severity?: string | null;
  filter?: string;
  filter_match_count?: number;
  helper_skill?: string;
  hide_disabled?: boolean;
  created_by_me?: boolean;
  /** Status of the linked inbox report, for `open_linked_report`. */
  report_status?: string;
}

export interface SignalSourceConnectedProperties {
  source_product: SourceProduct;
  /** True when this is a brand-new createSignalSourceConfig, false for re-enable of an existing config. */
  is_first_connection: boolean;
  /** True when the connection went through the DataSourceSetup wizard (warehouse OAuth path). */
  via_setup_wizard: boolean;
}

// Agents page events (the `/code/agents` configuration surface)
export type AgentsActionType = "run_setup_agent" | "open_mcp_servers";

export interface AgentsViewedProperties {
  /** Whether code access (GitHub) is connected — gates responder configuration. */
  has_github_integration: boolean;
  /** Total number of responder source products on the page. */
  responder_total_count: number;
  /** How many of those responders are currently enabled. */
  responder_enabled_count: number;
  /** User's PR auto-start threshold priority (P0–P4), or null when set to "Never". */
  autostart_priority: string | null;
  /** Whether the agent-driven setup entry point is shown (feature-flagged). */
  setup_task_available: boolean;
}

export interface AgentsActionProperties {
  action_type: AgentsActionType;
  /** Whether `run_setup_agent` successfully created the setup task. */
  success?: boolean;
}

// ── Project Bluebird / Channels (Website) space events ──

/** Where within the Channels space an interaction originated. */
export type ChannelsSurface =
  | "header_button"
  | "title_bar"
  | "nav"
  | "sidebar"
  | "command_menu"
  | "new_task"
  | "task_input"
  | "channel_home"
  | "channel_history"
  | "channel_artifacts"
  | "pinned"
  | "dashboards_grid"
  | "canvas"
  | "context"
  | "thread_panel"
  | "activity";

export type ChannelActionType =
  | "enter_space"
  | "leave_space"
  | "toggle_channels"
  | "leave_feedback"
  | "nav_click"
  | "open_channel"
  | "collapse_channel"
  | "view_more_tasks"
  | "create"
  | "rename"
  | "delete"
  | "star"
  | "unstar"
  | "edit_context_open"
  | "new_task_open"
  | "new_task_suggestion"
  | "view_context"
  | "view_history"
  | "view_artifacts"
  | "open_artifact"
  | "file_task"
  | "unfile_task"
  | "archive_task"
  | "open_task"
  | "collapse_thread"
  | "expand_thread"
  | "copy_link"
  | "mention_member"
  | "view_activity"
  | "open_mention"
  | "canvas_mode_toggle";

export interface ChannelActionProperties {
  action_type: ChannelActionType;
  surface: ChannelsSurface;
  /** The channel acted on, when one is in scope. */
  channel_id?: string;
  /** For file/unfile/archive/open task actions; for copy_link of a thread. */
  task_id?: string;
  /** For file_task: destination channel when different from `channel_id`. */
  target_channel_id?: string;
  /** For nav_click: which destination ("home"|"activity"|"inbox"|"canvas"|"agents"|"files"|"settings"). */
  nav_target?: string;
  /** For mention_member: the tagged teammate's user uuid. */
  mentioned_user_id?: string;
  /** For new_task_suggestion: the starter-prompt card label. */
  suggestion_label?: string;
  /** For canvas_mode_toggle: whether canvas mode is being armed. */
  armed?: boolean;
  /** Whether the underlying mutation resolved successfully. */
  success?: boolean;
}

export type DashboardActionType =
  | "open"
  | "create"
  | "delete"
  | "rename"
  | "save"
  | "fork"
  | "edit_toggle"
  | "revert"
  | "refresh"
  | "poll_mode_change"
  | "date_range_apply"
  | "link_copied"
  | "pin"
  | "unpin";

export interface DashboardActionProperties {
  action_type: DashboardActionType;
  surface: ChannelsSurface;
  channel_id?: string;
  dashboard_id?: string;
  /** The canvas render kind. */
  kind?: "json-render" | "freeform";
  /** Template chosen on create. */
  template_id?: string;
  /** edit_toggle: the state being entered. */
  editing?: boolean;
  /** poll_mode_change: the new value ("static"|"10s"|"10min"). */
  poll_mode?: string;
  /** date_range_apply: the named range, when not custom. */
  range_name?: string;
  /** Whether the underlying mutation resolved successfully. */
  success?: boolean;
}

export type CanvasPromptSurface = "json" | "freeform";

export interface CanvasPromptSentProperties {
  surface: CanvasPromptSurface;
  dashboard_id?: string;
  /** True when sent via a suggestion chip rather than free-typed. */
  from_suggestion: boolean;
  /** "ask_agent_to_fix" for the freeform self-repair path; absent otherwise. */
  intent?: "ask_agent_to_fix";
  prompt_length_chars: number;
}

export type ContextActionType = "save_version" | "generate_started" | "discard";

export interface ContextActionProperties {
  action_type: ContextActionType;
  channel_id: string;
  /** generate_started only. */
  execution_type?: "local" | "cloud";
  /** save_version: whether this created the first version vs. an update. */
  is_first_version?: boolean;
  success?: boolean;
}

export interface ChannelsSpaceViewedProperties {
  /** Total channels visible when the space mounts. */
  channel_count: number;
  starred_count: number;
}

// Subscription / billing events

export type UpgradePromptShownSurface =
  | "usage_limit_modal"
  | "titlebar_card"
  | "billing_announcement"
  | "model_picker";

export type UpgradePromptClickedSurface =
  | "usage_limit_modal"
  | "sidebar"
  | "titlebar"
  | "titlebar_card"
  | "plan_page_card"
  | "billing_announcement"
  | "model_picker";

export type UpgradePromptCause = "model_gate" | "org_limit";

export interface UpgradePromptShownProperties {
  surface: UpgradePromptShownSurface;
  cause?: UpgradePromptCause;
}

export interface UpgradePromptClickedProperties {
  surface: UpgradePromptClickedSurface;
  cause?: UpgradePromptCause;
}

export interface CloudTaskUsageBlockedProperties {
  bucket: "burst" | "sustained" | null;
  is_pro: boolean;
}

export interface UsageBillingAnnouncementAcknowledgedProperties {
  /** Stamps the acknowledgment on the person for support auditability. */
  $set: { code_usage_billing_acknowledged_at: string };
}

// Claude Code session import events
/** Where in the new-task suggestions the import was launched from. */
export type ClaudeSessionImportSource = "inline_card" | "picker_dialog";
/**
 * Import status of a listed CLI session. "imported" sessions are hidden from
 * the suggestions, so an import is only ever started from a "new" or "updated"
 * one; the wider union mirrors the domain status field.
 */
export type ClaudeSessionImportStatus = "new" | "imported" | "updated";

export interface ClaudeSessionsShownProperties {
  /** Resumable Claude Code CLI sessions surfaced for the repo. */
  sessions_count: number;
}

export interface ClaudeSessionImportedProperties {
  source: ClaudeSessionImportSource;
  session_status: ClaudeSessionImportStatus;
  has_git_branch: boolean;
  /** Resumable sessions available when this one was imported. */
  sessions_available_count: number;
}

export interface ClaudeSessionImportFailedProperties {
  source: ClaudeSessionImportSource;
  session_status: ClaudeSessionImportStatus;
  /** Saga step that failed, e.g. "import_claude_session" or "task_creation". */
  failed_step?: string;
}

/** Fired when a user arms autoresearch mode on the new-task composer. */
export interface AutoresearchArmedProperties {
  /** Hands-off mode auto-applied on arm so the unattended loop isn't blocked on permission prompts. */
  default_mode: "bypassPermissions" | "acceptEdits";
  workspace_mode?: "local" | "worktree" | "cloud";
}

/** Fired when an armed autoresearch task is submitted and its run kicks off. */
export interface AutoresearchRunStartedProperties {
  direction: "maximize" | "minimize";
  /** Whether the user set a target metric value to stop early at. */
  has_target: boolean;
  max_iterations: number;
  /** Build and measure stages differ, so each iteration splits into a build turn and a measure turn. */
  stages_split: boolean;
  implement_model?: string;
  measure_model?: string;
  implement_effort?: string;
  measure_effort?: string;
  workspace_mode?: "local" | "worktree" | "cloud";
}

// Loops events
type LoopReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max";
type LoopOverlapPolicy = "skip" | "allow" | "cancel_previous";
type LoopRunBlockedReason =
  | "deduped"
  | "overlap_skipped"
  | "rate_capped"
  | "team_rate_capped"
  | "disabled"
  | "gate_blocked"
  | "owner_inactive"
  | "owner_changed";
type LoopRunStatus =
  | "not_started"
  | "queued"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled";

export interface LoopListViewedProperties {
  loop_count: number;
  personal_loop_count: number;
  team_loop_count: number;
  is_at_limit: boolean;
  /** Backend-enforced per-project cap; omitted while the limit is still loading. */
  loop_limit?: number;
  builder_session_count: number;
}

export interface LoopViewedProperties {
  loop_id: string;
  visibility: "personal" | "team";
  enabled: boolean;
  /** Backend-open string; null when enabled or manually paused with no reason given. */
  disabled_reason: string | null;
  runtime_adapter: "claude" | "codex";
  model?: string;
  reasoning_effort: LoopReasoningEffort | null;
  repository_count: number;
  trigger_count: number;
  has_schedule_trigger: boolean;
  has_github_trigger: boolean;
  has_api_trigger: boolean;
  /** Backend-open string, not a closed enum. */
  last_run_status: string | null;
  consecutive_failures: number;
  recent_run_count: number;
}

export interface LoopSavedProperties {
  loop_id: string;
  visibility: "personal" | "team";
  runtime_adapter: "claude" | "codex";
  model?: string;
  reasoning_effort: LoopReasoningEffort | null;
  repository_count: number;
  trigger_count: number;
  has_schedule_trigger: boolean;
  has_github_trigger: boolean;
  has_api_trigger: boolean;
  is_pr_creation_enabled: boolean;
  is_auto_fix_enabled: boolean;
  /** Count of notifications.{push,email,slack} that are enabled. */
  notification_channel_count: number;
  has_context_target: boolean;
}

export interface LoopDeletedProperties {
  loop_id: string;
  visibility: "personal" | "team";
  enabled: boolean;
  trigger_count: number;
  /** State at time of deletion, distinguishes deleting a healthy loop from abandoning a failing one. */
  consecutive_failures: number;
}

export interface LoopEnabledToggledProperties {
  loop_id: string;
  /** The new value the loop is being switched to. */
  enabled: boolean;
  visibility: "personal" | "team";
  /** True when this toggle clears or reinstates a backend auto-pause rather than a routine manual pause/resume. */
  was_auto_paused: boolean;
  success: boolean;
}

export interface LoopRunStartedProperties {
  loop_id: string;
  task_id: string | null;
  task_run_id: string | null;
  runtime_adapter: "claude" | "codex";
  model?: string;
  trigger_count: number;
}

export interface LoopRunBlockedProperties {
  loop_id: string;
  reason: LoopRunBlockedReason;
  overlap_policy: LoopOverlapPolicy;
  trigger_count: number;
}

export interface LoopRunViewedProperties {
  loop_id: string;
  run_id: string;
  task_id: string;
  status: LoopRunStatus;
  environment: "local" | "cloud";
  /** True when the run wasn't triggered by a schedule/github/api trigger. */
  is_manual_run: boolean;
}

// Event names as constants
export const ANALYTICS_EVENTS = {
  // App lifecycle
  APP_STARTED: "App started",
  APP_QUIT: "App quit",

  // Authentication
  USER_LOGGED_IN: "User logged in",
  USER_LOGGED_OUT: "User logged out",

  // Task management
  TASK_LIST_VIEWED: "Task list viewed",
  TASK_CREATED: "Task created",
  TASK_VIEWED: "Task viewed",
  TASK_RUN: "Task run",
  TASK_RUN_STARTED: "Task run started",
  TASK_RUN_COMPLETED: "Task run completed",
  TASK_RUN_CANCELLED: "Task run cancelled",
  TASK_RUN_STOPPED: "Task run stopped",
  PROMPT_SENT: "Prompt sent",

  // Claude Code session import
  CLAUDE_SESSIONS_SHOWN: "Claude Code sessions shown",
  CLAUDE_SESSION_IMPORTED: "Claude Code session imported",
  CLAUDE_SESSION_IMPORT_FAILED: "Claude Code session import failed",

  // Repository
  REPOSITORY_SELECTED: "Repository selected",

  // Git operations
  GIT_ACTION_EXECUTED: "Git action executed",
  PR_CREATED: "PR created",
  AGENT_FILE_ACTIVITY: "Agent file activity",
  BRANCH_LINKED: "Branch linked",
  BRANCH_UNLINKED: "Branch unlinked",
  BRANCH_LINK_DEFAULT_BRANCH_UNKNOWN: "Branch link default branch unknown",

  // File interactions
  FILE_OPENED: "File opened",
  FILE_DIFF_VIEWED: "File diff viewed",
  REVIEW_PANEL_VIEWED: "Review panel viewed",
  DIFF_VIEW_MODE_CHANGED: "Diff view mode changed",

  // Workspace events
  WORKSPACE_CREATED: "Workspace created",
  WORKSPACE_SCRIPTS_STARTED: "Workspace scripts started",
  FOLDER_REGISTERED: "Folder registered",

  // Navigation events
  SETTINGS_VIEWED: "Settings viewed",
  COMMAND_MENU_OPENED: "Command menu opened",
  COMMAND_MENU_ACTION: "Command menu action",
  COMMAND_CENTER_VIEWED: "Command center viewed",
  BRAINROT_ACTIVATED: "Brainrot activated",
  SKILL_BUTTON_TRIGGERED: "Skill button triggered",
  POSTHOG_WEB_OPENED: "PostHog web opened",
  SIDEBAR_NAV_ITEM_CLICKED: "Sidebar nav item clicked",
  SIDEBAR_CUSTOMIZED: "Sidebar customized",
  SIDEBAR_REORDERED: "Sidebar reordered",

  // Permission events
  PERMISSION_RESPONDED: "Permission responded",
  PERMISSION_CANCELLED: "Permission cancelled",

  // Session config events
  SESSION_CONFIG_CHANGED: "Session config changed",

  // Settings events
  SETTING_CHANGED: "Setting changed",
  CUSTOM_SOUND_ADDED: "Custom sound added",
  CUSTOM_SOUND_RECORDING_SILENT: "Custom sound recording silent",

  // Feedback events
  TASK_FEEDBACK: "Task feedback",

  // Branch mismatch events
  BRANCH_MISMATCH_WARNING_SHOWN: "Branch mismatch warning shown",
  BRANCH_MISMATCH_ACTION: "Branch mismatch action",

  // Tour events
  TOUR_EVENT: "Tour event",

  // Onboarding events
  ONBOARDING_STARTED: "Onboarding started",
  ONBOARDING_STEP_VIEWED: "Onboarding step viewed",
  ONBOARDING_STEP_COMPLETED: "Onboarding step completed",
  ONBOARDING_STEP_SKIPPED: "Onboarding step skipped",
  ONBOARDING_SIGN_IN_INITIATED: "Onboarding sign in initiated",
  ONBOARDING_PROJECT_SELECTED: "Onboarding project selected",
  ONBOARDING_INVITE_CODE_SUBMITTED: "Onboarding invite code submitted",
  ONBOARDING_FOLDER_SELECTED: "Onboarding folder selected",
  ONBOARDING_GITHUB_CONNECT_STARTED: "Onboarding github connect started",
  ONBOARDING_GITHUB_CONNECT_FAILED: "Onboarding github connect failed",
  ONBOARDING_GITHUB_CONNECTED: "Onboarding github connected",
  ONBOARDING_CLI_CHECK_COMPLETED: "Onboarding cli check completed",
  ONBOARDING_CLI_RUN_COMPLETED: "Onboarding cli run completed",
  ONBOARDING_COMPLETED: "Onboarding completed",
  ONBOARDING_ABANDONED: "Onboarding abandoned",
  AI_CONSENT_GATE_SHOWN: "Ai consent gate shown",
  AI_CONSENT_APPROVED: "Ai consent approved",
  AI_CONSENT_GRANTED_INAPP: "Ai consent granted in-app",

  // Setup / onboarding events
  SETUP_DISCOVERY_STARTED: "Setup discovery started",
  SETUP_DISCOVERY_COMPLETED: "Setup discovery completed",
  SETUP_DISCOVERY_FAILED: "Setup discovery failed",
  SETUP_TASK_SELECTED: "Setup task selected",
  SETUP_TASK_DISMISSED: "Setup task dismissed",

  // Deep link events
  DEEP_LINK_NEW_TASK: "Deep link new task",
  DEEP_LINK_PLAN: "Deep link plan",
  DEEP_LINK_ISSUE: "Deep link issue",
  DEEP_LINK_ISSUE_FAILED: "Deep link issue failed",
  DEEP_LINK_CANVAS: "Deep link canvas",
  DEEP_LINK_CHANNEL: "Deep link channel",

  // Error events
  TASK_CREATION_FAILED: "Task creation failed",
  AGENT_SESSION_ERROR: "Agent session error",
  CLOUD_STREAM_DISCONNECTED: "Cloud stream disconnected",

  // Inbox events
  INBOX_VIEWED: "Inbox viewed",
  INBOX_REPORT_OPENED: "Inbox report opened",
  INBOX_REPORT_CLOSED: "Inbox report closed",
  INBOX_REPORT_ACTION: "Inbox report action",
  INBOX_REPORT_SCROLLED: "Inbox report scrolled",
  SIGNAL_SOURCE_CONNECTED: "Signal source connected",

  // Agents page events
  AGENTS_VIEWED: "Agents viewed",
  AGENTS_ACTION: "Agents action",

  // Scout events
  SCOUT_FLEET_VIEWED: "Scout fleet viewed",
  SCOUT_DETAIL_VIEWED: "Scout detail viewed",
  SCOUT_CONFIG_CHANGED: "Scout config changed",
  SCOUT_CHAT_STARTED: "Scout chat started",
  SCOUT_ACTION: "Scout action",

  // Usage and spend analysis events
  USAGE_VIEWED: "Usage viewed",
  SPEND_ANALYSIS_TASK_OPENED: "Spend analysis task opened",

  // Prompt history events
  PROMPT_HISTORY_OPENED: "Prompt history opened",
  PROMPT_HISTORY_SELECTED: "Prompt history selected",

  // Subscription events
  UPGRADE_PROMPT_SHOWN: "Upgrade prompt shown",
  UPGRADE_PROMPT_CLICKED: "Upgrade prompt clicked",
  CLOUD_TASK_USAGE_BLOCKED: "Cloud task usage blocked",
  USAGE_BILLING_ANNOUNCEMENT_ACKNOWLEDGED:
    "Usage billing announcement acknowledged",

  // Project Bluebird (Channels) events
  CHANNELS_SPACE_VIEWED: "Channels space viewed",
  CHANNEL_ACTION: "Channel action",
  DASHBOARD_ACTION: "Dashboard action",
  CANVAS_PROMPT_SENT: "Canvas prompt sent",
  CONTEXT_ACTION: "Context action",

  // Autoresearch events
  AUTORESEARCH_ARMED: "Autoresearch armed",
  AUTORESEARCH_RUN_STARTED: "Autoresearch run started",

  // Loops promo events
  LOOPS_PROMO_OPENED: "Loops promo opened",
  LOOPS_PROMO_DISMISSED: "Loops promo dismissed",
  LOOPS_PROMO_LEARN_MORE_CLICKED: "Loops promo learn more clicked",

  // Loops events
  LOOP_LIST_VIEWED: "Loop list viewed",
  LOOP_VIEWED: "Loop viewed",
  LOOP_CREATED: "Loop created",
  LOOP_UPDATED: "Loop updated",
  LOOP_DELETED: "Loop deleted",
  LOOP_ENABLED_TOGGLED: "Loop enabled toggled",
  LOOP_RUN_STARTED: "Loop run started",
  LOOP_RUN_BLOCKED: "Loop run blocked",
  LOOP_RUN_VIEWED: "Loop run viewed",
} as const;

// Event property mapping
export type EventPropertyMap = {
  [ANALYTICS_EVENTS.TASK_LIST_VIEWED]: TaskListViewProperties | undefined;
  [ANALYTICS_EVENTS.TASK_CREATED]: TaskCreateProperties;
  [ANALYTICS_EVENTS.TASK_VIEWED]: TaskViewProperties;
  [ANALYTICS_EVENTS.TASK_RUN]: TaskRunProperties;
  [ANALYTICS_EVENTS.REPOSITORY_SELECTED]: RepositorySelectProperties;
  [ANALYTICS_EVENTS.USER_LOGGED_IN]: UserIdentifyProperties | undefined;
  [ANALYTICS_EVENTS.USER_LOGGED_OUT]: never;

  // Task execution events
  [ANALYTICS_EVENTS.TASK_RUN_STARTED]: TaskRunStartedProperties;
  [ANALYTICS_EVENTS.TASK_RUN_COMPLETED]: TaskRunCompletedProperties;
  [ANALYTICS_EVENTS.TASK_RUN_CANCELLED]: TaskRunCancelledProperties;
  [ANALYTICS_EVENTS.TASK_RUN_STOPPED]: TaskRunStoppedProperties;
  [ANALYTICS_EVENTS.PROMPT_SENT]: PromptSentProperties;

  // Claude Code session import
  [ANALYTICS_EVENTS.CLAUDE_SESSIONS_SHOWN]: ClaudeSessionsShownProperties;
  [ANALYTICS_EVENTS.CLAUDE_SESSION_IMPORTED]: ClaudeSessionImportedProperties;
  [ANALYTICS_EVENTS.CLAUDE_SESSION_IMPORT_FAILED]: ClaudeSessionImportFailedProperties;

  // Git operations
  [ANALYTICS_EVENTS.GIT_ACTION_EXECUTED]: GitActionExecutedProperties;
  [ANALYTICS_EVENTS.PR_CREATED]: PrCreatedProperties;
  [ANALYTICS_EVENTS.AGENT_FILE_ACTIVITY]: AgentFileActivityProperties;
  [ANALYTICS_EVENTS.BRANCH_LINKED]: BranchLinkedProperties;
  [ANALYTICS_EVENTS.BRANCH_UNLINKED]: BranchUnlinkedProperties;
  [ANALYTICS_EVENTS.BRANCH_LINK_DEFAULT_BRANCH_UNKNOWN]: BranchLinkDefaultBranchUnknownProperties;

  // File interactions
  [ANALYTICS_EVENTS.FILE_OPENED]: FileOpenedProperties;
  [ANALYTICS_EVENTS.FILE_DIFF_VIEWED]: FileDiffViewedProperties;
  [ANALYTICS_EVENTS.REVIEW_PANEL_VIEWED]: ReviewPanelViewedProperties;
  [ANALYTICS_EVENTS.DIFF_VIEW_MODE_CHANGED]: DiffViewModeChangedProperties;

  // Workspace events
  [ANALYTICS_EVENTS.WORKSPACE_CREATED]: WorkspaceCreatedProperties;
  [ANALYTICS_EVENTS.WORKSPACE_SCRIPTS_STARTED]: WorkspaceScriptsStartedProperties;
  [ANALYTICS_EVENTS.FOLDER_REGISTERED]: FolderRegisteredProperties;

  // Navigation events
  [ANALYTICS_EVENTS.SETTINGS_VIEWED]: never;
  [ANALYTICS_EVENTS.COMMAND_MENU_OPENED]: never;
  [ANALYTICS_EVENTS.COMMAND_MENU_ACTION]: CommandMenuActionProperties;
  [ANALYTICS_EVENTS.COMMAND_CENTER_VIEWED]: never;
  [ANALYTICS_EVENTS.BRAINROT_ACTIVATED]: BrainrotActivatedProperties;
  [ANALYTICS_EVENTS.SKILL_BUTTON_TRIGGERED]: SkillButtonTriggeredProperties;
  [ANALYTICS_EVENTS.POSTHOG_WEB_OPENED]: never;
  [ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED]: SidebarNavItemClickedProperties;
  [ANALYTICS_EVENTS.SIDEBAR_CUSTOMIZED]: SidebarCustomizedProperties;
  [ANALYTICS_EVENTS.SIDEBAR_REORDERED]: SidebarReorderedProperties;

  // Permission events
  [ANALYTICS_EVENTS.PERMISSION_RESPONDED]: PermissionRespondedProperties;
  [ANALYTICS_EVENTS.PERMISSION_CANCELLED]: PermissionCancelledProperties;

  // Session config events
  [ANALYTICS_EVENTS.SESSION_CONFIG_CHANGED]: SessionConfigChangedProperties;

  // Settings events
  [ANALYTICS_EVENTS.SETTING_CHANGED]: SettingChangedProperties;
  [ANALYTICS_EVENTS.CUSTOM_SOUND_ADDED]: CustomSoundAddedProperties;
  [ANALYTICS_EVENTS.CUSTOM_SOUND_RECORDING_SILENT]: never;

  // Feedback events
  [ANALYTICS_EVENTS.TASK_FEEDBACK]: TaskFeedbackProperties;

  // Branch mismatch events
  [ANALYTICS_EVENTS.BRANCH_MISMATCH_WARNING_SHOWN]: BranchMismatchWarningShownProperties;
  [ANALYTICS_EVENTS.BRANCH_MISMATCH_ACTION]: BranchMismatchActionProperties;

  // Tour events
  [ANALYTICS_EVENTS.TOUR_EVENT]: TourEventProperties;

  // Onboarding events
  [ANALYTICS_EVENTS.ONBOARDING_STARTED]: never;
  [ANALYTICS_EVENTS.ONBOARDING_STEP_VIEWED]: OnboardingStepViewedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_STEP_COMPLETED]: OnboardingStepCompletedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_STEP_SKIPPED]: OnboardingStepSkippedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_SIGN_IN_INITIATED]: OnboardingSignInInitiatedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_PROJECT_SELECTED]: OnboardingProjectSelectedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_INVITE_CODE_SUBMITTED]: OnboardingInviteCodeSubmittedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_FOLDER_SELECTED]: OnboardingFolderSelectedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECT_STARTED]: OnboardingGithubConnectStartedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECT_FAILED]: OnboardingGithubConnectFailedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECTED]: never;
  [ANALYTICS_EVENTS.ONBOARDING_CLI_CHECK_COMPLETED]: OnboardingCliCheckCompletedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_CLI_RUN_COMPLETED]: OnboardingCliRunCompletedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_COMPLETED]: OnboardingCompletedProperties;
  [ANALYTICS_EVENTS.ONBOARDING_ABANDONED]: OnboardingAbandonedProperties;
  [ANALYTICS_EVENTS.AI_CONSENT_GATE_SHOWN]: AiConsentGateShownProperties;
  [ANALYTICS_EVENTS.AI_CONSENT_APPROVED]: never;
  [ANALYTICS_EVENTS.AI_CONSENT_GRANTED_INAPP]: never;

  // Setup / onboarding events
  [ANALYTICS_EVENTS.SETUP_DISCOVERY_STARTED]: SetupDiscoveryStartedProperties;
  [ANALYTICS_EVENTS.SETUP_DISCOVERY_COMPLETED]: SetupDiscoveryCompletedProperties;
  [ANALYTICS_EVENTS.SETUP_DISCOVERY_FAILED]: SetupDiscoveryFailedProperties;
  [ANALYTICS_EVENTS.SETUP_TASK_SELECTED]: SetupTaskSelectedProperties;
  [ANALYTICS_EVENTS.SETUP_TASK_DISMISSED]: SetupTaskDismissedProperties;

  // Deep link events
  [ANALYTICS_EVENTS.DEEP_LINK_NEW_TASK]: DeepLinkNewTaskProperties;
  [ANALYTICS_EVENTS.DEEP_LINK_PLAN]: DeepLinkPlanProperties;
  [ANALYTICS_EVENTS.DEEP_LINK_ISSUE]: DeepLinkIssueProperties;
  [ANALYTICS_EVENTS.DEEP_LINK_ISSUE_FAILED]: DeepLinkIssueFailedProperties;
  [ANALYTICS_EVENTS.DEEP_LINK_CANVAS]: DeepLinkCanvasProperties;
  [ANALYTICS_EVENTS.DEEP_LINK_CHANNEL]: DeepLinkChannelProperties;

  // Error events
  [ANALYTICS_EVENTS.TASK_CREATION_FAILED]: TaskCreationFailedProperties;
  [ANALYTICS_EVENTS.AGENT_SESSION_ERROR]: AgentSessionErrorProperties;
  [ANALYTICS_EVENTS.CLOUD_STREAM_DISCONNECTED]: CloudStreamDisconnectedProperties;

  // Inbox events
  [ANALYTICS_EVENTS.INBOX_VIEWED]: InboxViewedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_OPENED]: InboxReportOpenedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_CLOSED]: InboxReportClosedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_ACTION]: InboxReportActionProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_SCROLLED]: InboxReportScrolledProperties;
  [ANALYTICS_EVENTS.SIGNAL_SOURCE_CONNECTED]: SignalSourceConnectedProperties;

  // Agents page events
  [ANALYTICS_EVENTS.AGENTS_VIEWED]: AgentsViewedProperties;
  [ANALYTICS_EVENTS.AGENTS_ACTION]: AgentsActionProperties;

  // Scout events
  [ANALYTICS_EVENTS.SCOUT_FLEET_VIEWED]: ScoutFleetViewedProperties;
  [ANALYTICS_EVENTS.SCOUT_DETAIL_VIEWED]: ScoutDetailViewedProperties;
  [ANALYTICS_EVENTS.SCOUT_CONFIG_CHANGED]: ScoutConfigChangedProperties;
  [ANALYTICS_EVENTS.SCOUT_CHAT_STARTED]: ScoutChatStartedProperties;
  [ANALYTICS_EVENTS.SCOUT_ACTION]: ScoutActionProperties;

  // Usage and spend analysis events
  [ANALYTICS_EVENTS.USAGE_VIEWED]: UsageViewedProperties;
  [ANALYTICS_EVENTS.SPEND_ANALYSIS_TASK_OPENED]: SpendAnalysisTaskOpenedProperties;

  // Prompt history events
  [ANALYTICS_EVENTS.PROMPT_HISTORY_OPENED]: PromptHistoryOpenedProperties;
  [ANALYTICS_EVENTS.PROMPT_HISTORY_SELECTED]: PromptHistorySelectedProperties;

  // Subscription events
  [ANALYTICS_EVENTS.UPGRADE_PROMPT_SHOWN]: UpgradePromptShownProperties;
  [ANALYTICS_EVENTS.UPGRADE_PROMPT_CLICKED]: UpgradePromptClickedProperties;
  [ANALYTICS_EVENTS.USAGE_BILLING_ANNOUNCEMENT_ACKNOWLEDGED]: UsageBillingAnnouncementAcknowledgedProperties;
  [ANALYTICS_EVENTS.CLOUD_TASK_USAGE_BLOCKED]: CloudTaskUsageBlockedProperties;

  // Project Bluebird (Channels) events
  [ANALYTICS_EVENTS.CHANNELS_SPACE_VIEWED]: ChannelsSpaceViewedProperties;
  [ANALYTICS_EVENTS.CHANNEL_ACTION]: ChannelActionProperties;
  [ANALYTICS_EVENTS.DASHBOARD_ACTION]: DashboardActionProperties;
  [ANALYTICS_EVENTS.CANVAS_PROMPT_SENT]: CanvasPromptSentProperties;
  [ANALYTICS_EVENTS.CONTEXT_ACTION]: ContextActionProperties;

  // Autoresearch events
  [ANALYTICS_EVENTS.AUTORESEARCH_ARMED]: AutoresearchArmedProperties;
  [ANALYTICS_EVENTS.AUTORESEARCH_RUN_STARTED]: AutoresearchRunStartedProperties;

  // Loops promo events
  [ANALYTICS_EVENTS.LOOPS_PROMO_OPENED]: never;
  [ANALYTICS_EVENTS.LOOPS_PROMO_DISMISSED]: never;
  [ANALYTICS_EVENTS.LOOPS_PROMO_LEARN_MORE_CLICKED]: never;

  // Loops events
  [ANALYTICS_EVENTS.LOOP_LIST_VIEWED]: LoopListViewedProperties;
  [ANALYTICS_EVENTS.LOOP_VIEWED]: LoopViewedProperties;
  [ANALYTICS_EVENTS.LOOP_CREATED]: LoopSavedProperties;
  [ANALYTICS_EVENTS.LOOP_UPDATED]: LoopSavedProperties;
  [ANALYTICS_EVENTS.LOOP_DELETED]: LoopDeletedProperties;
  [ANALYTICS_EVENTS.LOOP_ENABLED_TOGGLED]: LoopEnabledToggledProperties;
  [ANALYTICS_EVENTS.LOOP_RUN_STARTED]: LoopRunStartedProperties;
  [ANALYTICS_EVENTS.LOOP_RUN_BLOCKED]: LoopRunBlockedProperties;
  [ANALYTICS_EVENTS.LOOP_RUN_VIEWED]: LoopRunViewedProperties;
};

/**
 * The inbox event family. Every host stamps an `inbox_client` property (e.g.
 * "code" on desktop, "mobile" on the mobile app, "cloud" on the PostHog web
 * frontend) on exactly these events so the shared PostHog project can be sliced
 * by surface. Mirrors posthog's `frontend/src/scenes/inbox/inboxAnalytics.ts`.
 *
 * Keep this in sync with the inbox entries in `EventPropertyMap` above.
 */
export const INBOX_ANALYTICS_EVENT_NAMES: ReadonlySet<string> = new Set([
  ANALYTICS_EVENTS.INBOX_VIEWED,
  ANALYTICS_EVENTS.INBOX_REPORT_OPENED,
  ANALYTICS_EVENTS.INBOX_REPORT_CLOSED,
  ANALYTICS_EVENTS.INBOX_REPORT_ACTION,
  ANALYTICS_EVENTS.INBOX_REPORT_SCROLLED,
  ANALYTICS_EVENTS.SIGNAL_SOURCE_CONNECTED,
]);

/** True when `eventName` is an inbox event that should carry `inbox_client`. */
export function isInboxAnalyticsEvent(eventName: string): boolean {
  return INBOX_ANALYTICS_EVENT_NAMES.has(eventName);
}
