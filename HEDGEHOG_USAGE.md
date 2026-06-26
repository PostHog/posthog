# Hedgehog image usage

An inventory of every image in [`frontend/public/hedgehog/`](frontend/public/hedgehog/) — what it maps to and where it's used.

Most hogs are exposed as named React components from [`frontend/src/lib/components/hedgehogs.tsx`](frontend/src/lib/components/hedgehogs.tsx) (the central registry).
A few are imported directly by a single component. Nothing references hogs by `/static/hedgehog/<name>.png` string path any more.
The Hogfetti confetti animation ([`Hogfetti/hogs/`](frontend/src/lib/components/Hogfetti/hogs/)), the Flappy Hog game ([`shared/flappy-hog/`](frontend/src/scenes/onboarding/shared/flappy-hog/)), and the 368Hedgehogs game ([`368Hedgehogs/sprites/`](products/games/368Hedgehogs/sprites/)) bundle their own hog copies locally rather than referencing the registry or `/static/` paths — those self-contained copies are tracked in the [Hogfetti pool](#hogfetti-pool-15), [Flappy Hog assets](#flappy-hog-assets-2), and [368Hedgehogs assets](#368hedgehogs-assets-4) sections below, not in the table, since they no longer consume `public/hedgehog/` and sit outside this replacement effort.

We want to retire these hedgehogs and replace them with illustrations from [`@posthog/brand`](https://brand.posthog.com/hoggies) (import via `@posthog/brand/hoggies`). The **Replacement** column holds the brand hoggie slug to swap in; it's per usage site, since different surfaces may want different art. A blank cell means the brand library has no suitable equivalent yet — those gaps are enumerated, with briefs for the design team, under [Missing from the brand library](#missing-from-the-brand-library) at the bottom.

> "Used" means actually rendered/consumed somewhere — not merely imported into the registry. Each usage site is its own row.
>
> Generated build artifacts (`frontend/dist/`, `frontend/toolbar-esbuild-meta.json`) reference most files but are ignored here.

## Used (39)

| Image                   | Used via                   | Usage site                                                                                        | Replacement        |
| ----------------------- | -------------------------- | ------------------------------------------------------------------------------------------------- | ------------------ |
| `builder-hog-01.png`    | `BuilderHog1`              | `frontend/src/scenes/surveys/SurveyViewRedesign/SurveyDraftContent.tsx`                           | `construction-1`   |
| `builder-hog-01.png`    | `BuilderHog1`              | `frontend/src/scenes/onboarding/shared/utils.tsx` (product onboarding intro)                      | `construction-1`   |
| `builder-hog-02.png`    | `BuilderHog2`              | `frontend/src/scenes/session-recordings/player/PurePlayer.tsx`                                    | `construction-2`   |
| `builder-hog-02.png`    | `BuilderHog2`              | `products/replay_vision/frontend/replay_scanners/ScannerEditorScene.tsx`                          | `construction-2`   |
| `builder-hog-03.png`    | `BuilderHog3`              | `frontend/src/scenes/insights/EmptyStates/EmptyStates.tsx`                                        | `construction-2`   |
| `builder-hog-03.png`    | `BuilderHog3`              | `frontend/src/scenes/billing/BillingEarlyAccessBanner.tsx`                                        | `construction-2`   |
| `builder-hog-03.png`    | `BuilderHog3`              | `frontend/src/lib/components/ProductIntroduction/ProductIntroduction.tsx`                         | `construction-2`   |
| `builder-hog-03.png`    | `BuilderHog3`              | `frontend/src/lib/components/TaxonomicFilter/TaxonomicFilterEmptyState.tsx`                       | `construction-2`   |
| `builder-hog-03.png`    | `BuilderHog3`              | `products/workflows/frontend/OptOuts/OptOutCategories.tsx`                                        | `construction-2`   |
| `list-hog.png`          | `ListHog`                  | `frontend/src/scenes/cohorts/Cohorts.tsx`                                                         | `greek`            |
| `list-hog.png`          | `ListHog`                  | `products/metrics/frontend/components/MetricsSetupPrompt.tsx`                                     | `greek`            |
| `list-hog.png`          | `ListHog`                  | `products/workflows/frontend/Workflows/WorkflowMetrics.tsx`                                       | `greek`            |
| `list-hog.png`          | `ListHog`                  | `products/workflows/frontend/Workflows/WorkflowLogs.tsx`                                          | `greek`            |
| `list-hog.png`          | `ListHog`                  | `products/logs/frontend/components/SetupPrompt/SetupPrompt.tsx`                                   | `greek`            |
| `blushing-hog.png`      | direct import              | `products/data_warehouse/frontend/shared/components/SourceIcon.tsx` (default source icon)         | `ipad`             |
| `robot-hog.png`         | `RobotHog`                 | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 | `robo-hog`         |
| `robot-hog.png`         | `RobotHog`                 | `frontend/src/exporter/scenes/ExporterInterviewScene.tsx`                                         | `robo-hog`         |
| `robot-hog.png`         | `RobotHog`                 | `products/user_interviews/frontend/TranscriptChat.tsx`                                            | `robo-hog`         |
| `robot-hog.png`         | `RobotHog`                 | `products/ai_gateway/frontend/AIGatewayScene.tsx`                                                 | `robo-hog`         |
| `running-hog.png`       | `RunningHog`               | `frontend/src/scenes/web-analytics/achievements/WebAnalyticsAchievementsModal.tsx`                | `coffee-run`       |
| `running-hog.png`       | direct import (`IconHTTP`) | `frontend/src/scenes/data-pipelines/batch-exports/BatchExportIcon.tsx` (HTTP batch-export icon)   | `coffee-run`       |
| `burning-money-hog.png` | `BurningMoneyHog`          | `frontend/src/scenes/billing/CreditCTAHero.tsx`                                                   |                    |
| `burning-money-hog.png` | `BurningMoneyHog`          | `products/customer_analytics/frontend/components/Accounts/AccountBillingExpansion.tsx`            |                    |
| `sleeping-hog.png`      | `SleepingHog`              | `frontend/src/scenes/health/components/PlatformStatusBanner.tsx`                                  | `driving-hogzilla` |
| `sleeping-hog.png`      | `SleepingHog`              | `frontend/src/scenes/authentication/verify-email/variants/paper-desk/PaperDeskVerifyEmail.tsx`    |                    |
| `warning-hog.png`       | `WarningHog`               | `frontend/src/scenes/health/components/PlatformStatusBanner.tsx`                                  |                    |
| `warning-hog.png`       | `WarningHog`               | `frontend/src/scenes/session-recordings/SessionRecordings.tsx`                                    |                    |
| `warning-hog.png`       | `WarningHog`               | `frontend/src/scenes/session-recordings/player/PurePlayer.tsx`                                    |                    |
| `warning-hog.png`       | `WarningHog`               | `frontend/src/scenes/billing/BillingEmptyState.tsx`                                               |                    |
| `warning-hog.png`       | `WarningHog`               | `frontend/src/layout/navigation-3000/sidepanel/panels/discussion/SidePanelDiscussion.tsx`         |                    |
| `warning-hog.png`       | `WarningHog`               | `products/error_tracking/frontend/components/SetupPrompt/SetupPrompt.tsx`                         |                    |
| `surprised-hog.png`     | `SurprisedHog`             | `frontend/src/scenes/wizard/Wizard.tsx`                                                           | `shocked`          |
| `surprised-hog.png`     | `SurprisedHog`             | `frontend/src/scenes/surveys/SurveyNoResponsesBanner.tsx`                                         | `shocked`          |
| `surprised-hog.png`     | `SurprisedHog`             | `frontend/src/scenes/authentication/email-mfa-verify/EmailMFAVerify.tsx`                          | `shocked`          |
| `surprised-hog.png`     | `SurprisedHog`             | `frontend/src/scenes/authentication/verify-email/variants/legacy/LegacyVerifyEmail.tsx`           | `shocked`          |
| `x-ray-hog.png`         | `XRayHog`                  | `products/tracing/frontend/components/SetupPrompt/SetupPrompt.tsx`                                | `x-ray`            |
| `x-ray-hog.png`         | `XRayHog`                  | `products/replay_vision/frontend/replay_scanners/ScannerEditorScene.tsx`                          | `x-ray`            |
| `x-ray-hog.png`         | `XRayHog`                  | `products/replay_vision/frontend/replay_scanners/ReplayScannersScene.tsx`                         | `x-ray`            |
| `x-ray-hog.png`         | `XRayHog`                  | `products/replay_vision/frontend/replay_scanners/components/VisionActionsTab.tsx`                 | `x-ray`            |
| `x-ray-hogs-02.png`     | `XRayHog2`                 | `frontend/src/scenes/web-analytics/PageReports.tsx`                                               | `x-ray`            |
| `hog-welder.png`        | `HogWelder`                | `frontend/src/scenes/organization/PendingDeletion.tsx`                                            |                    |
| `hog-welder.png`        | `HogWelder`                | `frontend/src/scenes/project/PendingDeletion.tsx`                                                 |                    |
| `laptop-hog-03.png`     | `LaptopHog3`               | `frontend/src/lib/components/UpgradeModal/UpgradeModal.tsx`                                       | `remote-work`      |
| `laptop-hog-04.png`     | `LaptopHog4`               | `frontend/src/lib/components/BridgePage/BridgePage.tsx`                                           | `haha-bizzniss`    |
| `laptop-hog-eu.png`     | `LaptopHogEU`              | `frontend/src/lib/components/BridgePage/BridgePage.tsx` (EU-region variant)                       | `haha-bizzniss`    |
| `explorer-hog.png`      | `ExplorerHog`              | `frontend/src/scenes/web-analytics/achievements/WebAnalyticsAchievementsModal.tsx`                |                    |
| `explorer-hog.png`      | `ExplorerHog`              | `frontend/src/scenes/authentication/verify-email/variants/paper-desk/PaperDeskVerifyEmail.tsx`    |                    |
| `explorer-hog.png`      | `ExplorerHog`              | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 |                    |
| `explorer-hog.png`      | `ExplorerHog`              | `products/customer_analytics/frontend/components/CustomerJourneys/CustomerJourneysEmptyState.tsx` |                    |
| `heart-hog.png`         | `HeartHog`                 | `frontend/src/scenes/health/components/PlatformStatusBanner.tsx`                                  |                    |
| `heart-hog.png`         | `HeartHog`                 | `frontend/src/scenes/wizard/Wizard.tsx`                                                           |                    |
| `heart-hog.png`         | `HeartHog`                 | `frontend/src/scenes/web-analytics/achievements/WebAnalyticsAchievementsModal.tsx`                |                    |
| `heart-hog.png`         | `HeartHog`                 | `frontend/src/scenes/authentication/email-mfa-verify/EmailMFAVerify.tsx`                          |                    |
| `heart-hog.png`         | `HeartHog`                 | `frontend/src/scenes/authentication/verify-email/variants/legacy/LegacyVerifyEmail.tsx`           |                    |
| `heart-hog.png`         | `HeartHog`                 | `frontend/src/scenes/authentication/account/credential-review/CredentialReview.tsx`               |                    |
| `heart-hog.png`         | `HeartHog`                 | `frontend/src/scenes/billing/UnsubscribeSurveyModal.tsx`                                          |                    |
| `heart-hog.png`         | `HeartHog`                 | `frontend/src/scenes/onboarding/legacy/billing/PlanCards.tsx`                                     |                    |
| `star-hog.png`          | `StarHog`                  | `frontend/src/scenes/web-analytics/achievements/WebAnalyticsAchievementsModal.tsx`                |                    |
| `star-hog.png`          | `StarHog`                  | `frontend/src/scenes/web-analytics/tiles/WebAnalyticsTile.tsx`                                    |                    |
| `star-hog.png`          | `StarHog`                  | `frontend/src/scenes/surveys/wizard/MaxTip.tsx`                                                   |                    |
| `star-hog.png`          | `StarHog`                  | `frontend/src/scenes/billing/Billing.tsx`                                                         |                    |
| `professor-hog.png`     | `ProfessorHog`             | `frontend/src/scenes/surveys/wizard/MaxTip.tsx`                                                   | `einstein`         |
| `professor-hog.png`     | `ProfessorHog`             | `frontend/src/scenes/surveys/components/empty-state/FirstSurveyHelper.tsx`                        | `einstein`         |
| `support-hero-hog.png`  | `SupportHeroHog`           | `frontend/src/scenes/data-pipelines/ZendeskSourceSetupPrompt.tsx`                                 |                    |
| `support-hero-hog.png`  | `SupportHeroHog`           | `products/conversations/frontend/components/ConversationsDisabledBanner.tsx`                      |                    |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/audit-logs/ExportsList.tsx`                                                  | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/audit-logs/AdvancedActivityLogsList.tsx`                                     | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/settings/user/LoginSessions.tsx`                                             | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/settings/user/ConnectedApps.tsx`                                             | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/subscriptions/SubscriptionsScene.tsx`                                        | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/web-analytics/achievements/WebAnalyticsAchievementsModal.tsx`                | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/surveys/SurveyNoResponsesBanner.tsx`                                         | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/surveys/wizard/MaxTip.tsx`                                                   | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/heatmaps/components/HeatmapsBrowser.tsx`                                     | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/authentication/verify-email/variants/paper-desk/PaperDeskVerifyEmail.tsx`    | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/lib/components/Alerts/views/Alerts.tsx`                                             | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `frontend/src/lib/components/ProductIntroduction/ProductIntroduction.tsx`                         | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `products/visual_review/frontend/scenes/VisualReviewRunScene.tsx`                                 | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `products/logs/frontend/components/VirtualizedLogsList/VirtualizedLogsList.tsx`                   | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `products/customer_analytics/frontend/components/Accounts/AccountBillingExpansion.tsx`            | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `products/dashboards/frontend/widgets/activity/ActivityEventsWidget.tsx`                          | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `products/dashboards/frontend/widgets/logs/LogsWidget.tsx`                                        | `magnifying-glass` |
| `detective-hog.png`     | `DetectiveHog`             | `products/replay_vision/frontend/replay_scanners/ScannerEditorScene.tsx`                          | `magnifying-glass` |
| `mail-hog.png`          | `MailHog`                  | `frontend/src/scenes/surveys/components/SurveyNotificationsList.tsx`                              |                    |
| `mail-hog.png`          | `MailHog`                  | `frontend/src/scenes/surveys/components/SurveyNotifications.tsx`                                  |                    |
| `mail-hog.png`          | `MailHog`                  | `frontend/src/scenes/authentication/verify-email/variants/legacy/LegacyVerifyEmail.tsx`           |                    |
| `mail-hog.png`          | `MailHog`                  | `frontend/src/scenes/onboarding/legacy/exit/OnboardingExitModal.tsx`                              |                    |
| `mail-hog.png`          | `MailHog`                  | `frontend/src/scenes/onboarding/legacy/exit/OnboardingExitAction.tsx`                             |                    |
| `mail-hog.png`          | `MailHog`                  | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 |                    |
| `mail-hog.png`          | `MailHog`                  | `products/workflows/frontend/Workflows/WorkflowsTable.tsx`                                        |                    |
| `feature-flag-hog.png`  | `FeatureFlagHog`           | `frontend/src/scenes/feature-flags/FeatureFlags.tsx`                                              |                    |
| `feature-flag-hog.png`  | `FeatureFlagHog`           | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 |                    |
| `experiments-hog.png`   | `ExperimentsHog`           | `frontend/src/scenes/experiments/Experiments.tsx`                                                 | `experiment`       |
| `experiments-hog.png`   | `ExperimentsHog`           | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 | `experiment`       |
| `experiments-hog.png`   | `ExperimentsHog`           | `frontend/src/scenes/moveToPostHogCloud/MoveToPostHogCloud.tsx`                                   | `experiment`       |
| `experiments-hog.png`   | `ExperimentsHog`           | `products/dashboards/frontend/widgets/experiments/ExperimentsListWidget.tsx`                      | `experiment`       |
| `experiments-hog.png`   | `ExperimentsHog`           | `products/dashboards/frontend/widgets/experiments/ExperimentResultsWidget.tsx`                    | `experiment`       |
| `waving-hog.png`        | `WavingHog`                | `frontend/src/scenes/web-analytics/achievements/WebAnalyticsAchievementsModal.tsx`                |                    |
| `waving-hog.png`        | `WavingHog`                | `frontend/src/scenes/surveys/SurveyNoResponsesBanner.tsx`                                         |                    |
| `reading-hog.png`       | `ReadingHog`               | `frontend/src/scenes/data-management/ingestion-warnings/IngestionWarningsView.tsx`                | `reading-is-magic` |
| `reading-hog.png`       | `ReadingHog`               | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 | `reading-is-magic` |
| `reading-hog.png`       | `ReadingHog`               | `products/workflows/frontend/TemplateLibrary/MessageTemplatesTable.tsx`                           | `reading-is-magic` |
| `microphone-hog.png`    | `MicrophoneHog`            | `frontend/src/scenes/data-management/comments/Comments.tsx`                                       | `reporter`         |
| `microphone-hog.png`    | `MicrophoneHog`            | `frontend/src/scenes/annotations/Annotations.tsx`                                                 | `reporter`         |
| `microphone-hog.png`    | `MicrophoneHog`            | `frontend/src/scenes/surveys/wizard/MaxTip.tsx`                                                   | `reporter`         |
| `microphone-hog.png`    | `MicrophoneHog`            | `frontend/src/scenes/surveys/components/empty-state/SurveysEmptyState.tsx`                        | `reporter`         |
| `microphone-hog.png`    | `MicrophoneHog`            | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 | `reporter`         |
| `microphone-hog.png`    | `MicrophoneHog`            | `products/workflows/frontend/Channels/MessageChannels.tsx`                                        | `reporter`         |
| `phone-pair-hogs.png`   | `PhonePairHogs`            | `frontend/src/scenes/comments/CommentsList.tsx`                                                   | `phone-call`       |
| `filmcamera.png`        | `FilmCameraHog`            | `frontend/src/scenes/marketing-analytics/Onboarding/Onboarding.tsx`                               | `director`         |
| `filmcamera.png`        | `FilmCameraHog`            | `frontend/src/scenes/session-recordings/playlist/SessionRecordingsPlaylist.tsx`                   | `director`         |
| `filmcamera.png`        | `FilmCameraHog`            | `frontend/src/scenes/heatmaps/scenes/heatmap/HeatmapScene.tsx`                                    | `director`         |
| `filmcamera.png`        | `FilmCameraHog`            | `frontend/src/scenes/onboarding/legacy/OnboardingSessionReplayConfiguration.tsx`                  | `director`         |
| `filmcamera.png`        | `FilmCameraHog`            | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 | `director`         |
| `filmcamera.png`        | `FilmCameraHog`            | `frontend/src/lib/components/TakeScreenshot/ScreenShotEditor.tsx`                                 | `director`         |
| `filmcamera.png`        | `FilmCameraHog`            | `products/dashboards/frontend/widgets/session_replay/SessionReplayWidget.tsx`                     | `director`         |
| `superman-hog.png`      | `SupermanHog`              | `frontend/src/scenes/onboarding/legacy/billing/OnboardingUpgradeStep.tsx`                         |                    |
| `superman-hog.png`      | `SupermanHog`              | `frontend/src/lib/components/Superpowers/Superpowers.tsx`                                         |                    |
| `superman-hog.png`      | `SupermanHog`              | `products/dashboards/frontend/widgets/error_tracking/ErrorTrackingWidget.tsx`                     |                    |
| `judge-hog.png`         | `JudgeHog`                 | `frontend/src/scenes/feature-flags/ApprovalsPromoBanner.tsx`                                      | `judge`            |
| `judge-hog.png`         | `JudgeHog`                 | `frontend/src/scenes/authentication/invite-signup/variants/paper-desk/PaperDeskInviteSignup.tsx`  | `judge`            |
| `judge-hog.png`         | `JudgeHog`                 | `frontend/src/scenes/billing/Billing.tsx`                                                         | `judge`            |
| `judge-hog.png`         | `JudgeHog`                 | `products/ai_observability/frontend/evaluations/EvaluationTemplates.tsx`                          | `judge`            |
| `climber-hog-01.png`    | `ClimberHog1`              | `frontend/src/scenes/startups/StartupProgram.tsx`                                                 |                    |
| `climber-hog-02.png`    | `ClimberHog2`              | `frontend/src/scenes/startups/StartupProgram.tsx`                                                 |                    |
| `yc-hog.png`            | `YCHog`                    | `frontend/src/scenes/startups/StartupProgram.tsx` (YC offer)                                      | `hogpatch`         |
| `big-leagues.png`       | `BigLeaguesHog`            | `frontend/src/lib/components/PayGateMini/AddonTrialModal.tsx`                                     |                    |
| `big-leagues.png`       | `BigLeaguesHog`            | `products/endpoints/frontend/EndpointsScene.tsx`                                                  |                    |
| `big-leagues.png`       | `BigLeaguesHog`            | `products/customer_analytics/frontend/components/Accounts/AccountOpportunitiesExpansion.tsx`      |                    |
| `stop-sign-hog.png`     | `StopSignHog`              | `frontend/src/scenes/organization/Deactivated.tsx`                                                | `stop`             |
| `graphs-hog.png`        | `GraphsHog`                | `frontend/src/scenes/dashboard/EmptyDashboardComponent.tsx`                                       | `chart-hog`        |
| `graphs-hog.png`        | `GraphsHog`                | `frontend/src/scenes/dashboard/dashboards/Dashboards.tsx`                                         | `chart-hog`        |
| `graphs-hog.png`        | `GraphsHog`                | `frontend/src/scenes/web-analytics/achievements/WebAnalyticsAchievementsModal.tsx`                | `chart-hog`        |
| `graphs-hog.png`        | `GraphsHog`                | `frontend/src/scenes/onboarding/shared/utils.tsx`                                                 | `chart-hog`        |
| `graphs-hog.png`        | `GraphsHog`                | `products/dashboards/frontend/components/WidgetCard/WidgetCardBody.tsx`                           | `chart-hog`        |
| `graphs-hog.png`        | `GraphsHog`                | `frontend/src/lib/components/ProductIntroduction/ProductIntroduction.stories.tsx` (Storybook)     | `chart-hog`        |

## Unused (7)

Imported into [`hedgehogs.tsx`](frontend/src/lib/components/hedgehogs.tsx) and exported as components, but the components are never rendered anywhere in `frontend/` or `products/`.

| Image                       | Exported component   | Status                                                            |
| --------------------------- | -------------------- | ----------------------------------------------------------------- |
| `3-bears-hogs.png`          | `ThreeBearsHogs`     | Exported, never consumed                                          |
| `desk-hog.png`              | `DeskHog`            | Exported, never consumed                                          |
| `disguise-hog.png`          | `DisguiseHog`        | Exported, never consumed                                          |
| `hospital-hog.png`          | `HospitalHog`        | Exported, never consumed (was only in the Hogfetti pool; dropped) |
| `laptop-hog-01.png`         | `LaptopHog1`         | Exported, never consumed                                          |
| `laptop-hog-02.png`         | `LaptopHog2`         | Exported, never consumed                                          |
| `pop-up-binoculars-hog.png` | `PopUpBinocularsHog` | Exported, never consumed                                          |

## Hogfetti pool (15)

[`Hogfetti.tsx`](frontend/src/lib/components/Hogfetti/Hogfetti.tsx) bundles 15 hogs inline at 64×64 from its own [`hogs/`](frontend/src/lib/components/Hogfetti/hogs/) folder, independent of `public/hedgehog/` and the registry.
They're listed here rather than in the Used table because they no longer consume `public/hedgehog/` and fall outside the replacement effort.

| Image (in `Hogfetti/hogs/`) | Public original status                                                   |
| --------------------------- | ------------------------------------------------------------------------ |
| `surprised-hog.png`         | Still used elsewhere — see [Used](#used-39)                              |
| `blushing-hog.png`          | Still used elsewhere                                                     |
| `explorer-hog.png`          | Still used elsewhere                                                     |
| `running-hog.png`           | Still used elsewhere                                                     |
| `space-hog.png`             | ⚠ Hogfetti-only — `public/hedgehog/` original now unused, can be deleted |
| `tron-hog.png`              | ⚠ Hogfetti-only — `public/hedgehog/` original now unused, can be deleted |
| `heart-hog.png`             | Still used elsewhere                                                     |
| `star-hog.png`              | Still used elsewhere                                                     |
| `professor-hog.png`         | Still used elsewhere                                                     |
| `detective-hog.png`         | Still used elsewhere                                                     |
| `mail-hog.png`              | Still used elsewhere                                                     |
| `feature-flag-hog.png`      | Still used elsewhere                                                     |
| `experiments-hog.png`       | Still used elsewhere                                                     |
| `waving-hog.png`            | Still used elsewhere                                                     |
| `microphone-hog.png`        | Still used elsewhere                                                     |

## Flappy Hog assets (2)

The Flappy Hog game ([`FlappyHog.tsx`](frontend/src/scenes/onboarding/shared/FlappyHog.tsx)) bundles its art locally under [`shared/flappy-hog/`](frontend/src/scenes/onboarding/shared/flappy-hog/) instead of `public/hedgehog/`, so it's tracked here rather than in the Used table. These are bespoke game assets with no brand-library equivalent — keep them as-is.

| Asset (in `shared/flappy-hog/`) | Role               | `public/hedgehog/` original                                                            |
| ------------------------------- | ------------------ | -------------------------------------------------------------------------------------- |
| `flappy-hog-splash.png`         | Game splash screen | Moved out of `public/hedgehog/` (was Flappy-only) — original deleted                   |
| `robot-hog.png`                 | Playable character | Local copy; original stays in `public/hedgehog/` for the `RobotHog` registry component |

## 368Hedgehogs assets (4)

The 368Hedgehogs game ([`368Hedgehogs.tsx`](products/games/368Hedgehogs/368Hedgehogs.tsx)) bundles its four board sprites locally under [`368Hedgehogs/sprites/`](products/games/368Hedgehogs/sprites/) as tiny 128×128 copies instead of pulling the full-size originals from `public/hedgehog/` by `/static/` path, so they're tracked here rather than in the Used table. These are self-contained game sprites and sit outside the replacement effort — keep them as-is.

| Asset (in `368Hedgehogs/sprites/`) | Role        | `public/hedgehog/` original                                                                                            |
| ---------------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------- |
| `burning-money-hog.png`            | `hog1` tile | Local copy; original stays for the billing usages — see [Used](#used-39)                                               |
| `police-hog.png`                   | `hog2` tile | Local copy; the `public/hedgehog/` original was deleted (no remaining consumers) — see [Cleanup notes](#cleanup-notes) |
| `sleeping-hog.png`                 | `hog3` tile | Local copy; original stays for the platform-status & verify-email usages                                               |
| `warning-hog.png`                  | `hog4` tile | Local copy; original stays for the many error / empty-state usages — see [Used](#used-39)                              |

## Cleanup notes

**Orphaned `police-hog`** — once nothing referenced its `public/hedgehog/` original any more:

- **`public/hedgehog/police-hog.png`** was deleted (the 368Hedgehogs game keeps its own local sprite; the `PoliceHog` registry export was never rendered).
- The **`PoliceHog` registry export** in [`hedgehogs.tsx`](frontend/src/lib/components/hedgehogs.tsx) was removed along with it.

**Hogfetti move** — trimming the Hogfetti pool to 15 inline 64×64 copies left some dead weight in the registry:

- **`public/hedgehog/space-hog.png` and `public/hedgehog/tron-hog.png`** are now referenced only by their inline Hogfetti copies — the public originals can be deleted (also flagged in [Hogfetti pool](#hogfetti-pool-15)).
- **Dead registry exports** in [`hedgehogs.tsx`](frontend/src/lib/components/hedgehogs.tsx) (no remaining consumers): `SpaceHog`, `TronHog`, `HospitalHog`. Plus the six never-consumed exports `ThreeBearsHogs`, `DeskHog`, `DisguiseHog`, `LaptopHog1`, `LaptopHog2`, `PopUpBinocularsHog`.

## Missing from the brand library

These current hogs have **no suitable `@posthog/brand` equivalent**, so they block a full retirement of `public/hedgehog/`. Each row is a brief for the design team: what to draw and where it's used so the intent is clear. Until these land in [`@posthog/brand`](https://brand.posthog.com/hoggies), the corresponding **Replacement** cells above stay blank.

| Needed hedgehog            | What it should depict (designer brief)                                                                                                                          | Replaces                           | Where it's used                                                                                              | Priority                         |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------- |
| Feature flag hog           | A hog raising a flag on a pole (current art waves a small checkered/marker flag). Must read unmistakably as a "flag" — it represents the Feature flags product. | `feature-flag-hog`                 | Feature flags list empty state, onboarding intro                                                             | High — product-defining          |
| Warning hog                | A hog with a caution sign (yellow ⚠ triangle) or an alarmed "something went wrong" look. This is the generic error / empty-state hog.                           | `warning-hog`                      | Session recordings, billing empty state, error tracking setup, discussion side panel, platform-status banner | High — used in many error states |
| Heart hog                  | A hog holding or hugging a red heart — affection, "we love you", health-OK, favourite.                                                                          | `heart-hog`                        | Health banner, billing unsubscribe, MFA & verify-email, plan cards, achievements                             | Medium                           |
| Star hog                   | A hog holding up a gold star — achievement, featured, favourite.                                                                                                | `star-hog`                         | Web analytics achievements, billing, surveys wizard tip                                                      | Medium                           |
| Waving hog                 | A friendly hog waving hello — greeting / welcome.                                                                                                               | `waving-hog`                       | Web analytics achievements, survey no-responses banner                                                       | Medium                           |
| Mail hog                   | A hog with an envelope, or beside a mailbox with letters — email / notifications.                                                                               | `mail-hog`                         | Survey notifications, email verification, onboarding exit, workflows table                                   | Medium                           |
| Explorer hog               | A hog as an explorer/hiker with a backpack and a map (current art) or binoculars — discovering / exploring.                                                     | `explorer-hog`                     | Achievements, onboarding intro, customer journeys empty state                                                | Medium                           |
| Superhero hog              | A hog in a superhero cape and heroic pose. One caped-hero design can cover both the flying "Superman" pose and the "support hero" variant.                      | `superman-hog`, `support-hero-hog` | Superpowers, onboarding upgrade, Zendesk source setup, conversations disabled banner                         | Medium                           |
| Climber hog                | A hog mountaineering / scaling a peak — ambition, scaling up. Ideally two poses (mid-climb and near-summit); the Startup program shows both side by side.       | `climber-hog-01`, `climber-hog-02` | Startup program                                                                                              | Low — single scene               |
| "Big leagues" signpost hog | A hog at a crossroads signpost (e.g. "Medium leagues →" / "Big leagues →") deciding to level up — growth / upsell.                                              | `big-leagues`                      | Add-on trial modal, endpoints upsell, account opportunities                                                  | Low                              |

**Deliberately not replaced** (keep current art / acceptable to leave blank — no new art requested): `burning-money-hog` (billing), `hog-welder` (pending-deletion screens), and the non-platform `sleeping-hog` usages (verify-email). The platform-status `sleeping-hog` is covered by `driving-hogzilla`. The 368Hedgehogs game sprites are out of scope entirely — see [368Hedgehogs assets](#368hedgehogs-assets-4).
