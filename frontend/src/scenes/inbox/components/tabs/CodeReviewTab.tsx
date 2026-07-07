import { useActions, useValues } from 'kea'

import {
    IconBalance,
    IconChevronDown,
    IconDirectedGraph,
    IconExternal,
    IconFilter,
    IconGithub,
    IconPlus,
    IconPullRequest,
    IconSearch,
    IconShield,
    IconStack,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonSkeleton,
    LemonSlider,
    LemonSwitch,
    LemonTabs,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand/Logomark'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import type {
    ReviewFindingApi,
    ReviewIssuePriorityEnumApi,
    ReviewPerspectiveStatItemApi,
    ReviewRecentReviewApi,
    UrgencyThresholdEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { ReviewDrawerTab, ReviewSkillKind, reviewHogSettingsLogic } from '../../logics/reviewHogSettingsLogic'

/** "review-hog-perspective-logic-correctness" → "Logic correctness" */
function prettifySkillName(skillName: string): string {
    const cleaned = skillName
        .replace(/^review-hog-(perspective|blind-spots|validation)-/, '')
        .replace(/[-_]/g, ' ')
        .trim()
    return cleaned ? cleaned.charAt(0).toUpperCase() + cleaned.slice(1) : skillName
}

const PIPELINE_PHASES: { name: string; hint: string; steps: { number: string; title: string; caption: string }[] }[] = [
    {
        name: 'Prepare',
        hint: 'get the diff ready to read',
        steps: [
            { number: '01', title: 'Changed code', caption: "we fetch the PR's diff" },
            {
                number: '02',
                title: 'Meaningful files',
                caption: 'generated files, lock files, and snapshots are skipped',
            },
            { number: '03', title: 'Chunks', caption: 'larger PRs are split into logically reviewable chunks' },
        ],
    },
    {
        name: 'Review',
        hint: 'read every chunk in parallel',
        steps: [
            { number: '04', title: 'Perspectives', caption: 'specialist reviewers read each chunk in parallel' },
            { number: '05', title: 'Blind spots', caption: 'one more sweep for what every perspective missed' },
        ],
    },
    {
        name: 'Refine & publish',
        hint: 'clean up and ship the review',
        steps: [
            { number: '06', title: 'Dedupe', caption: 'overlapping findings are merged' },
            { number: '07', title: 'Validate', caption: 'each finding is checked against your quality bar' },
            { number: '08', title: 'Publish', caption: 'a cleaned-up review lands on the pull request' },
        ],
    },
]

const URGENCY_STOPS: { key: UrgencyThresholdEnumApi; label: string; description: string }[] = [
    {
        key: 'consider',
        label: 'All issues',
        description: 'Every validated finding is published, including the minor consider-level ones.',
    },
    {
        key: 'should_fix',
        label: 'Should fix',
        description: 'Recommended fixes and anything more serious — the default balance.',
    },
    {
        key: 'must_fix',
        label: 'Must fix',
        description: 'Only blocking issues, the highest-priority findings. Everything else is dropped.',
    },
]

function SectionHeader({
    icon,
    title,
    pill,
    children,
}: {
    icon: JSX.Element
    title: string
    pill?: JSX.Element
    children: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-primary bg-surface-primary text-secondary *:size-4">
                    {icon}
                </span>
                <h3 className="m-0 text-base font-semibold">{title}</h3>
                {pill}
            </div>
            {/* Indented so the copy aligns under the title, not the icon tile */}
            <p className="m-0 ml-9 max-w-160 text-xs text-secondary">{children}</p>
        </div>
    )
}

/**
 * Hero proof block: the validation funnel across the user's recent reviews, summed from the same
 * stats the effectiveness cards use. Hidden for users with no reviewed findings yet.
 */
function ProofCard(): JSX.Element | null {
    const { perspectiveStats } = useValues(reviewHogSettingsLogic)

    if (perspectiveStats === null) {
        return <LemonSkeleton className="h-24 w-full" />
    }
    const raised = perspectiveStats.perspectives.reduce((sum, p) => sum + p.raised, 0)
    const kept = perspectiveStats.perspectives.reduce((sum, p) => sum + p.kept, 0)
    const dismissed = perspectiveStats.perspectives.reduce((sum, p) => sum + p.dismissed, 0)
    if (raised === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="mt-2 flex flex-col gap-3 p-5">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-3xl font-bold tabular-nums text-warning">{kept}</span>
                <span className="text-sm font-semibold">findings worth your time</span>
                <span className="text-xs text-secondary">
                    from <span className="font-semibold text-default">{raised}</span> raised ·{' '}
                    <span className="font-semibold text-default">{dismissed}</span> filtered as noise
                </span>
                <span className="ml-auto text-xxs text-tertiary">
                    Your last {perspectiveStats.report_count} review{perspectiveStats.report_count === 1 ? '' : 's'}
                </span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-fill-highlight-100">
                <div className="h-full rounded-full bg-warning" style={{ width: `${(kept / raised) * 100}%` }} />
            </div>
            <div className="flex items-center gap-4 text-xs text-tertiary">
                <span className="flex items-center gap-1.5">
                    <span className="inline-block size-2 rounded-full bg-warning" /> Worth your time
                </span>
                <span className="flex items-center gap-1.5">
                    <span className="inline-block size-2 rounded-full bg-border-bold" /> Filtered as noise
                </span>
            </div>
        </LemonCard>
    )
}

function PipelineSection(): JSX.Element {
    return (
        <section className="flex flex-col gap-4 border-t border-primary pt-8">
            <SectionHeader icon={<IconDirectedGraph />} title="How we review your PRs">
                Every review runs through the same steps before it's published.
            </SectionHeader>
            <div className="flex flex-wrap items-stretch gap-2.5">
                {PIPELINE_PHASES.map((phase, i) => (
                    <div key={phase.name} className="flex min-w-52 flex-1 items-center gap-2.5">
                        {i > 0 && <span className="shrink-0 text-lg text-tertiary">→</span>}
                        <LemonCard hoverEffect={false} className="flex h-full flex-1 flex-col gap-3 p-4">
                            <div className="flex flex-col">
                                <span className="text-sm font-semibold">{phase.name}</span>
                                <span className="text-xs text-tertiary">{phase.hint}</span>
                            </div>
                            <div className="flex flex-col gap-2.5">
                                {phase.steps.map((step) => (
                                    <div key={step.number} className="flex items-start gap-2">
                                        <span className="font-mono text-xxs text-warning">{step.number}</span>
                                        <div className="flex flex-col">
                                            <span className="text-xs font-semibold">{step.title}</span>
                                            <span className="text-xxs text-tertiary">{step.caption}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </LemonCard>
                    </div>
                ))}
            </div>
        </section>
    )
}

const PRIORITY_TAG: Record<ReviewIssuePriorityEnumApi, { type: 'danger' | 'warning' | 'muted'; label: string }> = {
    must_fix: { type: 'danger', label: 'Must fix' },
    should_fix: { type: 'warning', label: 'Should fix' },
    consider: { type: 'muted', label: 'Consider' },
}

/** "best_practice" → "Best practice" */
function prettifyCategory(category: string): string {
    const cleaned = category.replace(/_/g, ' ')
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
}

/** Scoreboard label for a finding's source skill — blind-spot skills all read as one sweep. */
function perspectiveLabel(skillName: string): string {
    if (skillName.startsWith('review-hog-blind-spots-')) {
        return 'Blind spots'
    }
    if (skillName === 'unknown') {
        return 'Unknown'
    }
    return prettifySkillName(skillName)
}

const COUNT_CHIPS: {
    key: 'must_fix_count' | 'should_fix_count' | 'consider_count'
    label: string
    dot: string
    text: string
}[] = [
    { key: 'must_fix_count', label: 'must fix', dot: 'bg-danger', text: 'text-danger' },
    { key: 'should_fix_count', label: 'should fix', dot: 'bg-warning', text: 'text-warning' },
    { key: 'consider_count', label: 'consider', dot: 'bg-border-bold', text: 'text-secondary' },
]

function FindingCounts({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    const total = review.must_fix_count + review.should_fix_count + review.consider_count
    if (total === 0) {
        return <span>No findings</span>
    }
    return (
        <span className="flex items-center gap-2.5">
            {COUNT_CHIPS.filter((chip) => review[chip.key] > 0).map((chip) => (
                <span key={chip.key} className="flex items-center gap-1 whitespace-nowrap">
                    <span className={`size-1.5 rounded-full ${chip.dot}`} />
                    <span className={`font-semibold tabular-nums ${chip.text}`}>{review[chip.key]}</span>
                    <span>{chip.label}</span>
                </span>
            ))}
        </span>
    )
}

/** Leading status dot: red when the review found a blocker, gold for other findings, green for a clean pass. */
function ReviewStatusDot({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    const total = review.must_fix_count + review.should_fix_count + review.consider_count
    const color = review.must_fix_count > 0 ? 'bg-danger' : total > 0 ? 'bg-warning' : 'bg-success'
    return (
        <span className="flex w-6 shrink-0 justify-center">
            <span className={`size-2 rounded-full ${color}`} />
        </span>
    )
}

function reviewTitle(review: ReviewRecentReviewApi): string {
    return review.pr_title ?? `${review.repository}#${review.pr_number ?? review.head_branch}`
}

function progressLabel(review: ReviewRecentReviewApi): string {
    if (!review.progress) {
        return 'Review in progress'
    }
    // Steps match the pipeline as users think of it: chunking → review → dedupe → validation.
    // Fetching folds into step 1; dedupe is inferred from "every chunk read, findings not judged yet".
    const { review_stage, done, total } = review.progress
    const percent = done !== null && total !== null && total > 0 ? ` · ${Math.round((done / total) * 100)}%` : ''
    switch (review_stage) {
        case 'fetching':
            return 'Step 1/4 · Preparing the diff'
        case 'chunking':
            return 'Step 1/4 · Splitting into chunks'
        case 'reviewing':
            if (done !== null && total !== null && total > 0 && done >= total) {
                return 'Step 3/4 · Merging overlapping findings'
            }
            return `Step 2/4 · Reviewing chunks${percent}`
        case 'validating':
            return `Step 4/4 · Validating findings${percent}`
    }
}

/** A first review still running: no findings to expand into yet, just the live stage. */
function RunningReviewRow({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    return (
        <div className="flex items-center gap-3 px-4 py-3">
            <span className="flex w-6 shrink-0 justify-center">
                <Spinner className="text-lg" />
            </span>
            <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{reviewTitle(review)}</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-secondary">
                    <span className="whitespace-nowrap font-mono text-tertiary">
                        {review.repository}#{review.pr_number ?? review.head_branch}
                    </span>
                    <span className="text-tertiary">·</span>
                    <span className="whitespace-nowrap font-medium text-warning">{progressLabel(review)}</span>
                </div>
            </div>
            <LemonButton size="small" type="secondary" to={review.github_url} targetBlank sideIcon={<IconExternal />}>
                {review.github_url.includes('/pull/') ? 'View PR' : 'View branch'}
            </LemonButton>
        </div>
    )
}

/** One expandable review row: essentials collapsed; PR facts + funnel + findings entry when open. */
function RecentReviewRow({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    const { expandedReviewIds } = useValues(reviewHogSettingsLogic)
    const { toggleReviewRowExpanded, openReviewDetail } = useActions(reviewHogSettingsLogic)
    const expanded = expandedReviewIds.includes(review.id)
    const validated = review.must_fix_count + review.should_fix_count + review.consider_count

    // A first review has no completed turn to expand into — it renders as a live progress row.
    if (review.in_progress && review.run_count === 0) {
        return <RunningReviewRow review={review} />
    }

    return (
        <div className="flex flex-col">
            <div
                role="button"
                tabIndex={0}
                aria-expanded={expanded}
                onClick={() => toggleReviewRowExpanded(review.id)}
                onKeyDown={(e) => e.key === 'Enter' && toggleReviewRowExpanded(review.id)}
                className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-fill-highlight-50"
            >
                <ReviewStatusDot review={review} />
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold">{reviewTitle(review)}</span>
                        {review.in_progress && (
                            <LemonTag type="warning" size="small" className="inline-flex items-center gap-1">
                                <Spinner className="text-xs" /> Re-reviewing · {progressLabel(review)}
                            </LemonTag>
                        )}
                        {!review.published && (
                            <LemonTag type="muted" size="small">
                                Not published
                            </LemonTag>
                        )}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-secondary">
                        <span className="whitespace-nowrap font-mono text-tertiary">
                            {review.repository}#{review.pr_number ?? review.head_branch}
                        </span>
                        <span className="text-tertiary">·</span>
                        <FindingCounts review={review} />
                        {review.last_run_at && (
                            <>
                                <span className="text-tertiary">·</span>
                                <TZLabel time={review.last_run_at} />
                            </>
                        )}
                    </div>
                </div>
                {/* stopPropagation so the buttons don't also toggle the row */}
                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <LemonButton
                        size="small"
                        type="secondary"
                        to={review.github_url}
                        targetBlank
                        sideIcon={<IconExternal />}
                    >
                        {review.github_url.includes('/pull/') ? 'View PR' : 'View branch'}
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="tertiary"
                        aria-label={expanded ? 'Hide review details' : 'Show review details'}
                        icon={<IconChevronDown className={expanded ? 'rotate-180' : ''} />}
                        onClick={() => toggleReviewRowExpanded(review.id)}
                    />
                </div>
            </div>
            {expanded && (
                <div className="flex flex-col gap-2 border-t border-primary bg-fill-highlight-50 py-3 pl-13 pr-4">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-secondary">
                        {review.pr_author && <span className="whitespace-nowrap">by {review.pr_author}</span>}
                        {review.additions !== null && review.deletions !== null && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap font-mono">
                                    <span className="text-success">+{review.additions}</span>{' '}
                                    <span className="text-danger">−{review.deletions}</span>
                                </span>
                            </>
                        )}
                        {review.changed_files !== null && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap">{review.changed_files} files changed</span>
                            </>
                        )}
                        {review.files_reviewed !== null && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap">{review.files_reviewed} reviewed</span>
                            </>
                        )}
                        {review.chunk_count !== null && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap">
                                    {review.chunk_count} chunk{review.chunk_count === 1 ? '' : 's'}
                                </span>
                            </>
                        )}
                        <span className="text-tertiary">·</span>
                        <span className="whitespace-nowrap">
                            {review.run_count} review turn{review.run_count === 1 ? '' : 's'}
                        </span>
                    </div>
                    <div className="text-xs text-secondary">
                        <span className="font-semibold text-default">{review.candidate_count}</span> findings raised →{' '}
                        <span className="font-semibold text-default">{validated}</span> kept after validation →{' '}
                        <span className="font-semibold text-default">{review.dismissed_count}</span> dismissed
                    </div>
                    <div>
                        <LemonButton size="small" type="secondary" onClick={() => openReviewDetail(review)}>
                            View findings
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

/** Compact proof-of-life block under the hero — hidden entirely until the user has reviews. */
function RecentReviewsSection(): JSX.Element | null {
    const { recentReviews } = useValues(reviewHogSettingsLogic)

    // Loaded-and-empty hides the section entirely; `null` means the first load is still in flight,
    // so a skeleton holds the space instead of the page jumping when the rows land. Poll refreshes
    // keep the previous rows, so the skeleton only ever shows once.
    if (recentReviews !== null && !recentReviews.length) {
        return null
    }

    return (
        // The one section without a top hairline — it reads as a continuation of the hero.
        <section className="flex flex-col gap-4">
            <SectionHeader icon={<IconPullRequest />} title="Your recent reviews">
                The latest ReviewHog runs on pull requests you authored. Expand a review for its details and findings.
            </SectionHeader>
            <LemonCard hoverEffect={false} className="divide-y divide-primary p-0">
                {recentReviews === null
                    ? [0, 1, 2].map((i) => (
                          <div key={i} className="flex items-center gap-3 px-4 py-3">
                              <span className="flex w-6 shrink-0 justify-center">
                                  <LemonSkeleton.Circle className="size-2" />
                              </span>
                              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                                  <LemonSkeleton className="h-4 w-80 max-w-full" />
                                  <LemonSkeleton className="h-3 w-56 max-w-full" />
                              </div>
                              <LemonSkeleton className="h-8 w-24 shrink-0" />
                          </div>
                      ))
                    : recentReviews.map((review) => <RecentReviewRow key={review.id} review={review} />)}
            </LemonCard>
        </section>
    )
}

type FindingSection = 'description' | 'suggestion' | 'validator'

function FindingCard({ finding, dismissed }: { finding: ReviewFindingApi; dismissed?: boolean }): JSX.Element {
    const { reviewDetail } = useValues(reviewHogSettingsLogic)
    const priority = PRIORITY_TAG[finding.effective_priority]
    const location = finding.lines.length
        ? `${finding.file}:${finding.lines.map((r) => (r.end && r.end !== r.start ? `${r.start}–${r.end}` : `${r.start}`)).join(', ')}`
        : finding.file
    const firstRange = finding.lines[0]
    // Deep link to the exact reviewed code: the head SHA pins the lines even after later pushes.
    const githubHref = reviewDetail?.head_sha
        ? `https://github.com/${reviewDetail.repository}/blob/${reviewDetail.head_sha}/${finding.file}` +
          (firstRange
              ? `#L${firstRange.start}${firstRange.end && firstRange.end !== firstRange.start ? `-L${firstRange.end}` : ''}`
              : '')
        : null
    return (
        <div className="flex flex-col gap-2 py-4">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type={dismissed ? 'muted' : priority.type} size="small">
                    {priority.label}
                </LemonTag>
                {finding.effective_priority !== finding.reviewer_priority && (
                    <LemonTag type="muted" size="small">
                        was {PRIORITY_TAG[finding.reviewer_priority].label.toLowerCase()}
                    </LemonTag>
                )}
                {finding.validator_category && (
                    <LemonTag type="muted" size="small">
                        {prettifyCategory(finding.validator_category)}
                    </LemonTag>
                )}
                {finding.source_perspective && (
                    <span className="text-xs text-tertiary">{prettifySkillName(finding.source_perspective)}</span>
                )}
            </div>
            <span className={`text-base font-semibold ${dismissed ? 'text-secondary' : ''}`}>{finding.title}</span>
            {githubHref ? (
                <Link
                    to={githubHref}
                    target="_blank"
                    className="self-start font-mono text-xs text-tertiary hover:text-default"
                >
                    {location}
                </Link>
            ) : (
                <span className="font-mono text-xs text-tertiary">{location}</span>
            )}
            {/* Collapsed by default, like the published PR comment — title + location scan, text on demand. */}
            <LemonCollapse<FindingSection>
                multiple
                size="small"
                panels={[
                    {
                        key: 'description',
                        header: 'Description',
                        content: <p className="m-0 text-sm text-secondary">{finding.body}</p>,
                    },
                    {
                        key: 'suggestion',
                        header: 'Suggested fix',
                        content: <p className="m-0 text-sm text-secondary">{finding.suggestion}</p>,
                    },
                    {
                        key: 'validator',
                        header: dismissed ? 'Why it was dismissed' : "Why we think it's a valid issue",
                        content: <p className="m-0 text-sm text-secondary">{finding.validator_note}</p>,
                    },
                ]}
            />
        </div>
    )
}

function DrawerFindingsSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-2.5">
            <LemonSkeleton className="h-24 w-full" />
            <LemonSkeleton className="h-24 w-full" />
            <LemonSkeleton className="h-24 w-full" />
        </div>
    )
}

/** The "Published" tab: only the findings that crossed the urgency threshold onto the PR. */
function DrawerPublishedTab(): JSX.Element {
    const { reviewFindingsSplit } = useValues(reviewHogSettingsLogic)

    if (!reviewFindingsSplit) {
        return <DrawerFindingsSkeleton />
    }
    if (!reviewFindingsSplit.published.length) {
        return (
            <div className="text-sm text-secondary">
                Nothing crossed your urgency threshold — no comments were posted to the pull request.
            </div>
        )
    }
    return (
        <div className="flex flex-col divide-y divide-primary">
            {reviewFindingsSplit.published.map((finding, i) => (
                <FindingCard key={i} finding={finding} />
            ))}
        </div>
    )
}

/** The "Below threshold" tab: findings the validator kept, but the user's urgency bar held back. */
function DrawerBelowThresholdTab(): JSX.Element {
    const { reviewFindingsSplit } = useValues(reviewHogSettingsLogic)

    if (!reviewFindingsSplit) {
        return <DrawerFindingsSkeleton />
    }
    if (!reviewFindingsSplit.belowThreshold.length) {
        return (
            <div className="text-sm text-secondary">
                Nothing was held back — every validated finding crossed your urgency threshold.
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">
                Validated as real, but under the bar you set — kept here instead of the pull request.
            </p>
            <div className="flex flex-col divide-y divide-primary">
                {reviewFindingsSplit.belowThreshold.map((finding, i) => (
                    <FindingCard key={i} finding={finding} />
                ))}
            </div>
        </div>
    )
}

/** The "Dismissed" tab: findings that failed validation, each with the validator's reasoning. */
function DrawerDismissedTab(): JSX.Element {
    const { reviewDetail } = useValues(reviewHogSettingsLogic)

    if (!reviewDetail) {
        return <DrawerFindingsSkeleton />
    }
    if (!reviewDetail.dismissed_findings.length) {
        return <div className="text-sm text-secondary">The validator dismissed nothing on this review.</div>
    }
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">
                Raised during review, judged not worth your time — each with the validator's reasoning.
            </p>
            <div className="flex flex-col divide-y divide-primary">
                {reviewDetail.dismissed_findings.map((finding, i) => (
                    <FindingCard key={i} finding={finding} dismissed />
                ))}
            </div>
        </div>
    )
}

function ReviewDetailDrawer(): JSX.Element {
    const {
        reviewDrawerOpen,
        openedReview,
        reviewDetail,
        reviewDrawerTab,
        reviewFindingsSplit,
        perspectiveScoreboard,
    } = useValues(reviewHogSettingsLogic)
    const { closeReviewDrawer, setReviewDrawerTab } = useActions(reviewHogSettingsLogic)

    // The list row carries the header facts, so the drawer opens instantly while findings load.
    const review = reviewDetail ?? openedReview

    return (
        <LemonDrawer
            isOpen={reviewDrawerOpen}
            onClose={closeReviewDrawer}
            title={review ? reviewTitle(review) : ''}
            description={
                review
                    ? `${review.repository}#${review.pr_number ?? review.head_branch}${
                          review.pr_author ? ` · by ${review.pr_author}` : ''
                      }`
                    : undefined
            }
            width={640}
            footer={
                review ? (
                    <LemonButton type="secondary" to={review.github_url} targetBlank icon={<IconExternal />}>
                        {review.github_url.includes('/pull/') ? 'View PR on GitHub' : 'View branch on GitHub'}
                    </LemonButton>
                ) : undefined
            }
        >
            <div className="flex flex-col gap-2">
                {reviewDetail ? (
                    <div className="text-sm text-secondary">
                        <span className="font-semibold text-default">{reviewDetail.candidate_count}</span> findings
                        raised · <span className="font-semibold text-default">{reviewDetail.findings.length}</span> kept
                        after validation ·{' '}
                        <span className="font-semibold text-default">{reviewDetail.dismissed_count}</span> dismissed by
                        your quality bar
                    </div>
                ) : (
                    <LemonSkeleton className="h-5 w-80" />
                )}
                {perspectiveScoreboard && (
                    <div className="flex flex-wrap items-center gap-1.5 text-xs text-secondary">
                        <span>Found by:</span>
                        {perspectiveScoreboard.map(({ skillName, count }) => (
                            <LemonTag key={skillName} type="muted" size="small">
                                {perspectiveLabel(skillName)} {count}
                            </LemonTag>
                        ))}
                    </div>
                )}
                <LemonTabs<ReviewDrawerTab>
                    activeKey={reviewDrawerTab}
                    onChange={setReviewDrawerTab}
                    tabs={[
                        {
                            key: 'published',
                            label: `Published${reviewFindingsSplit ? ` (${reviewFindingsSplit.published.length})` : ''}`,
                            content: <DrawerPublishedTab />,
                        },
                        {
                            key: 'below_threshold',
                            label: `Below threshold${
                                reviewFindingsSplit ? ` (${reviewFindingsSplit.belowThreshold.length})` : ''
                            }`,
                            content: <DrawerBelowThresholdTab />,
                        },
                        {
                            key: 'dismissed',
                            label: `Dismissed${reviewDetail ? ` (${reviewDetail.dismissed_findings.length})` : ''}`,
                            content: <DrawerDismissedTab />,
                        },
                        {
                            key: 'review',
                            label: 'Review body',
                            content: reviewDetail ? (
                                reviewDetail.report_markdown ? (
                                    <LemonMarkdown className="text-sm">{reviewDetail.report_markdown}</LemonMarkdown>
                                ) : (
                                    <div className="text-sm text-secondary">
                                        No review body was rendered for this pull request.
                                    </div>
                                )
                            ) : (
                                <LemonSkeleton className="h-40 w-full" />
                            ),
                        },
                    ]}
                />
            </div>
        </LemonDrawer>
    )
}

function TriggersSection(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)

    const switchDisabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined

    return (
        <section className="flex flex-col gap-4 border-t border-primary pt-8">
            <SectionHeader icon={<IconFilter />} title="What gets reviewed">
                Choose which pull requests ReviewHog picks up automatically.
            </SectionHeader>
            <LemonCard hoverEffect={false} className="divide-y divide-primary p-0">
                <div className="flex items-center gap-4 p-4">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded border border-primary bg-primary *:h-auto *:w-5">
                        <Logomark />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold">Review all your Inbox PRs</div>
                        <div className="text-xs text-secondary">
                            When a self-driving implementation from your Inbox opens a pull request, ReviewHog reviews
                            it and posts the review to the pull request automatically.
                        </div>
                    </div>
                    <LemonSwitch
                        aria-label="Review all your Inbox PRs"
                        checked={settings?.review_inbox_prs ?? false}
                        onChange={(checked) => updateSettings({ review_inbox_prs: checked })}
                        disabledReason={switchDisabledReason}
                    />
                </div>
                <div className="flex items-center gap-4 p-4">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded border border-primary bg-primary">
                        <IconGithub className="size-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold">
                            Review all your PRs with the{' '}
                            <CopyToClipboardInline
                                explicitValue="reviewhog"
                                description="label"
                                iconSize="xsmall"
                                className="rounded border border-warning bg-warning-highlight px-1.5 py-0.5 font-mono text-xs text-warning"
                            >
                                reviewhog
                            </CopyToClipboardInline>{' '}
                            label
                        </div>
                        <div className="text-xs text-secondary">
                            Add the reviewhog label to a pull request you author in a connected repository and ReviewHog
                            reviews it.
                        </div>
                    </div>
                    <LemonSwitch
                        aria-label="Review all your PRs with the reviewhog label"
                        checked={settings?.review_labeled_prs ?? true}
                        onChange={(checked) => updateSettings({ review_labeled_prs: checked })}
                        disabledReason={switchDisabledReason}
                    />
                </div>
            </LemonCard>
        </section>
    )
}

function UrgencySection(): JSX.Element {
    const { settings } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)

    const activeIndex = Math.max(
        0,
        URGENCY_STOPS.findIndex((stop) => stop.key === (settings?.urgency_threshold ?? 'should_fix'))
    )

    return (
        <section className="flex flex-col gap-4 border-t border-primary pt-8">
            <SectionHeader icon={<IconBalance />} title="Urgency threshold">
                Set how strict ReviewHog is. The further right, the fewer findings reach the pull request — but the
                higher their priority.
            </SectionHeader>
            <LemonCard hoverEffect={false} className="flex flex-col p-5">
                <LemonSlider
                    min={0}
                    max={2}
                    step={1}
                    value={activeIndex}
                    onChange={(value) => {
                        // LemonSlider fires per mousemove while dragging — only PATCH on a stop change.
                        if (value !== activeIndex) {
                            updateSettings({ urgency_threshold: URGENCY_STOPS[value].key })
                        }
                    }}
                    disabledReason={settings === null ? 'Loading…' : undefined}
                />
                <div className="mt-3 flex justify-between">
                    {URGENCY_STOPS.map((stop, i) => (
                        <button
                            key={stop.key}
                            type="button"
                            disabled={settings === null}
                            aria-pressed={i === activeIndex}
                            className={`cursor-pointer border-0 bg-transparent p-0 text-xs font-semibold ${
                                i === activeIndex ? 'text-default' : 'text-tertiary'
                            }`}
                            onClick={() => {
                                if (i !== activeIndex) {
                                    updateSettings({ urgency_threshold: stop.key })
                                }
                            }}
                        >
                            {stop.label}
                        </button>
                    ))}
                </div>
                <div className="mt-2 flex justify-between text-xxs text-tertiary">
                    <span>← every finding</span>
                    <span>only the most urgent →</span>
                </div>
                <div className="mt-3 border-t border-primary pt-3 text-xs text-secondary">
                    {URGENCY_STOPS[activeIndex].description}
                </div>
            </LemonCard>
        </section>
    )
}

interface SkillCardData {
    skill_name: string
    description: string
    body: string
    on: boolean
}

function SkillCard({
    skill,
    onLabel,
    offLabel,
    onToggle,
}: {
    skill: SkillCardData
    onLabel: string
    offLabel: string
    onToggle: (checked: boolean) => void
}): JSX.Element {
    const { savingSkillNames } = useValues(reviewHogSettingsLogic)
    const { viewSkill } = useActions(reviewHogSettingsLogic)
    const title = prettifySkillName(skill.skill_name)

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 flex-col gap-1.5">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold">{title}</span>
                        <LemonTag type={skill.on ? 'warning' : 'muted'} size="small">
                            {skill.on ? onLabel : offLabel}
                        </LemonTag>
                    </div>
                    <p className="m-0 max-w-130 text-xs text-secondary">{skill.description}</p>
                    <div className="flex items-center gap-2 text-xs">
                        <Link onClick={() => viewSkill({ title, body: skill.body, skillName: skill.skill_name })}>
                            View skill
                        </Link>
                        <span className="text-tertiary">·</span>
                        <Link
                            to={urls.skill(skill.skill_name)}
                            target="_blank"
                            className="inline-flex items-center gap-0.5"
                        >
                            Edit skill <IconExternal className="size-3" />
                        </Link>
                    </div>
                </div>
                <LemonSwitch
                    aria-label={title}
                    checked={skill.on}
                    onChange={onToggle}
                    disabledReason={savingSkillNames.includes(skill.skill_name) ? 'Saving…' : undefined}
                />
            </div>
        </LemonCard>
    )
}

function SkillListSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-2.5">
            <LemonSkeleton className="h-24 w-full" />
            <LemonSkeleton className="h-24 w-full" />
        </div>
    )
}

function CreateYourOwnButton({ kind, label }: { kind: ReviewSkillKind; label: string }): JSX.Element {
    const { creatingSkillKind } = useValues(reviewHogSettingsLogic)
    const { startSkillAuthorTask } = useActions(reviewHogSettingsLogic)
    return (
        <div>
            <LemonButton
                type="secondary"
                icon={<IconPlus />}
                onClick={() => startSkillAuthorTask(kind)}
                loading={creatingSkillKind === kind}
                disabledReason={
                    creatingSkillKind && creatingSkillKind !== kind ? 'Another authoring task is starting…' : undefined
                }
            >
                {label}
            </LemonButton>
        </div>
    )
}

function EffectivenessRows({
    items,
    maxRaised,
}: {
    items: ReviewPerspectiveStatItemApi[]
    maxRaised: number
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {items.map((stat) => (
                <Tooltip
                    key={stat.skill_name}
                    title={`${stat.raised} raised · ${stat.kept} kept · ${stat.dismissed} dismissed by validation`}
                >
                    <div className="flex items-center gap-3">
                        <span className="w-44 shrink-0 truncate text-xs">{prettifySkillName(stat.skill_name)}</span>
                        <div className="flex h-2 flex-1 items-center">
                            {stat.kept > 0 && (
                                <div
                                    className="h-2 rounded-sm bg-success"
                                    style={{ width: `${(stat.kept / maxRaised) * 100}%` }}
                                />
                            )}
                            {stat.dismissed > 0 && (
                                <div
                                    className="ml-0.5 h-2 rounded-sm bg-fill-highlight-100"
                                    style={{ width: `${(stat.dismissed / maxRaised) * 100}%` }}
                                />
                            )}
                        </div>
                        <span className="w-24 shrink-0 text-right text-xs tabular-nums text-secondary">
                            {stat.kept} of {stat.raised} kept
                        </span>
                    </div>
                </Tooltip>
            ))}
        </div>
    )
}

/**
 * Aggregate effectiveness across the user's recent reviews for one reviewer kind: per skill, a bar
 * of findings it raised split into validator-kept (green) vs dismissed (muted). Rendered once in
 * the Perspectives section and once in the Blind-spot section, above each one's skill cards; both
 * cards share one scale so bar lengths stay comparable. Hidden until there is data for the kind.
 */
function EffectivenessCard({ kind }: { kind: 'perspectives' | 'blind_spots' }): JSX.Element | null {
    const { perspectiveStats } = useValues(reviewHogSettingsLogic)

    if (!perspectiveStats?.perspectives.length) {
        return null
    }
    const items = perspectiveStats.perspectives.filter(
        (p) => p.skill_name.startsWith('review-hog-blind-spots-') === (kind === 'blind_spots')
    )
    if (!items.length) {
        return null
    }
    const maxRaised = Math.max(...perspectiveStats.perspectives.map((p) => p.raised))
    const noun = kind === 'blind_spots' ? 'sweep' : 'perspective'

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            {/* Overline header: this card is an instrument panel about the skills below, not one of
                them — it must not share the skill cards' title style. */}
            <div className="flex flex-col gap-1">
                <span className="text-xxs font-semibold uppercase tracking-wide text-tertiary">Effectiveness</span>
                <p className="m-0 text-xs text-secondary">
                    Findings each {noun} raised across your last {perspectiveStats.report_count} review
                    {perspectiveStats.report_count === 1 ? '' : 's'}, and how many survived validation.
                </p>
            </div>
            <EffectivenessRows items={items} maxRaised={maxRaised} />
            <div className="flex items-center gap-4 text-xs text-tertiary">
                <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-success" /> Kept
                </span>
                <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-fill-highlight-100" /> Dismissed by validation
                </span>
            </div>
        </LemonCard>
    )
}

/**
 * The validator's flip side of the effectiveness cards: one bar for the whole quality bar (verdicts
 * aren't attributed to a validator skill), with dismissals as the headline — its job is filtering.
 */
function ValidatorEffectivenessCard(): JSX.Element | null {
    const { perspectiveStats } = useValues(reviewHogSettingsLogic)

    if (!perspectiveStats?.perspectives.length) {
        return null
    }
    const kept = perspectiveStats.perspectives.reduce((sum, p) => sum + p.kept, 0)
    const dismissed = perspectiveStats.perspectives.reduce((sum, p) => sum + p.dismissed, 0)
    const judged = kept + dismissed
    if (judged === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            <div className="flex flex-col gap-1">
                <span className="text-xxs font-semibold uppercase tracking-wide text-tertiary">Effectiveness</span>
                <p className="m-0 text-xs text-secondary">
                    Of the {judged} findings your reviewers raised across your last {perspectiveStats.report_count}{' '}
                    review{perspectiveStats.report_count === 1 ? '' : 's'}, this is how much noise your quality bar kept
                    off your pull requests.
                </p>
            </div>
            <Tooltip title={`${judged} judged · ${kept} kept · ${dismissed} dismissed by validation`}>
                {/* Unlike the reviewer cards, green here is the DISMISSED share — this card celebrates noise removed. */}
                <div className="flex items-center gap-3">
                    <span className="w-44 shrink-0 truncate text-xs">Your quality bar</span>
                    <div className="flex h-2 flex-1 items-center">
                        {dismissed > 0 && (
                            <div
                                className="h-2 rounded-sm bg-success"
                                style={{ width: `${(dismissed / judged) * 100}%` }}
                            />
                        )}
                        {kept > 0 && (
                            <div
                                className="ml-0.5 h-2 rounded-sm bg-fill-highlight-100"
                                style={{ width: `${(kept / judged) * 100}%` }}
                            />
                        )}
                    </div>
                    <span className="w-24 shrink-0 text-right text-xs tabular-nums text-secondary">
                        {dismissed} of {judged} dismissed
                    </span>
                </div>
            </Tooltip>
            <div className="flex items-center gap-4 text-xs text-tertiary">
                <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-success" /> Dismissed by your bar
                </span>
                <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-fill-highlight-100" /> Kept
                </span>
            </div>
        </LemonCard>
    )
}

function PerspectivesSection(): JSX.Element {
    const { perspectives } = useValues(reviewHogSettingsLogic)
    const { togglePerspective } = useActions(reviewHogSettingsLogic)

    return (
        <section className="flex flex-col gap-4 border-t border-primary pt-8">
            <SectionHeader
                icon={<IconStack />}
                title="Perspectives"
                pill={
                    <LemonTag type="muted" size="small">
                        Enable as many as you like · at least one stays on
                    </LemonTag>
                }
            >
                Each perspective is a skill — an editable instruction set the reviewer follows. Toggles here apply only
                to reviews of your pull requests; editing a skill changes it for the whole team.
            </SectionHeader>
            <EffectivenessCard kind="perspectives" />
            {perspectives === null ? (
                <SkillListSkeleton />
            ) : (
                <div className="flex flex-col gap-2.5">
                    {perspectives.map((p) => (
                        <SkillCard
                            key={p.skill_name}
                            skill={{ ...p, on: p.enabled }}
                            onLabel="Enabled"
                            offLabel="Disabled"
                            onToggle={(checked) => togglePerspective(p.skill_name, checked)}
                        />
                    ))}
                </div>
            )}
            <CreateYourOwnButton kind="perspective" label="Create your own perspective" />
        </section>
    )
}

function SingleActiveSection({
    icon,
    title,
    intro,
    kind,
    kindLabel,
    createLabel,
    skills,
    onSelect,
    preamble,
}: {
    icon: JSX.Element
    title: string
    intro: string
    kind: ReviewSkillKind
    kindLabel: string
    createLabel: string
    skills: SkillCardData[] | null
    onSelect: (skillName: string) => void
    preamble?: JSX.Element
}): JSX.Element {
    const { blockSingleActiveDeactivation } = useActions(reviewHogSettingsLogic)

    return (
        <section className="flex flex-col gap-4 border-t border-primary pt-8">
            <SectionHeader
                icon={icon}
                title={title}
                pill={
                    <LemonTag type="warning" size="small">
                        One active at a time
                    </LemonTag>
                }
            >
                {intro}
            </SectionHeader>
            {preamble}
            {skills === null ? (
                <SkillListSkeleton />
            ) : (
                <div className="flex flex-col gap-2.5">
                    {skills.map((skill) => (
                        <SkillCard
                            key={skill.skill_name}
                            skill={skill}
                            onLabel="Active"
                            offLabel="Off"
                            onToggle={(checked) =>
                                checked ? onSelect(skill.skill_name) : blockSingleActiveDeactivation(kindLabel)
                            }
                        />
                    ))}
                </div>
            )}
            <CreateYourOwnButton kind={kind} label={createLabel} />
        </section>
    )
}

function SkillDrawer(): JSX.Element {
    const { viewedSkill, skillDrawerOpen } = useValues(reviewHogSettingsLogic)
    const { closeSkillDrawer } = useActions(reviewHogSettingsLogic)

    return (
        <LemonDrawer
            isOpen={skillDrawerOpen}
            onClose={closeSkillDrawer}
            title={viewedSkill?.title ?? ''}
            description="Skill · read-only"
            width={440}
            footer={
                <LemonButton
                    type="secondary"
                    to={viewedSkill ? urls.skill(viewedSkill.skillName) : urls.skills()}
                    targetBlank
                    icon={<IconExternal />}
                >
                    Open in Skills editor
                </LemonButton>
            }
        >
            <pre className="m-0 whitespace-pre-wrap font-mono text-xs leading-relaxed text-secondary">
                {viewedSkill?.body}
            </pre>
        </LemonDrawer>
    )
}

/**
 * The Inbox "Code review" tab: ReviewHog's combined onboarding and settings page. One scrollable
 * guided-configuration page — every control is live from load, no save step. See
 * `reviewHogSettingsLogic` for the data flow.
 */
export function CodeReviewTab(): JSX.Element {
    const { blindSpots, validators, initialLoadFailed } = useValues(reviewHogSettingsLogic)
    const { selectBlindSpots, selectValidator, loadAll } = useActions(reviewHogSettingsLogic)

    return (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 pb-30 pt-11">
            <section className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                    <span className="size-1.5 rounded-full bg-warning" />
                    <span className="text-xxs font-semibold uppercase tracking-widest text-tertiary">
                        Automated pull request review
                    </span>
                </div>
                <h2 className="m-0 text-3xl font-bold" style={{ textWrap: 'balance' }}>
                    ReviewHog reviews pull requests before humans do
                </h2>
                <p className="m-0 max-w-155 text-sm text-secondary">
                    Specialist review perspectives read your changed code in parallel, a blind-spot sweep catches what
                    they missed, and only validated findings get published back to the pull request.
                </p>
                <ProofCard />
            </section>

            {initialLoadFailed && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadAll() }}>
                    Some ReviewHog settings failed to load.
                </LemonBanner>
            )}

            <RecentReviewsSection />
            <PipelineSection />
            <TriggersSection />
            <UrgencySection />
            <PerspectivesSection />
            <SingleActiveSection
                icon={<IconSearch />}
                title="Blind-spot check"
                intro="After the enabled perspectives finish, ReviewHog runs one more sweep over each chunk — it sees what they found and hunts for real issues they all missed. Add as many sweeps as you like, but only one runs."
                kind="blind_spots"
                kindLabel="blind-spot check"
                preamble={<EffectivenessCard kind="blind_spots" />}
                createLabel="Create your own blind-spot check"
                skills={blindSpots?.map((s) => ({ ...s, on: s.active })) ?? null}
                onSelect={selectBlindSpots}
            />
            <SingleActiveSection
                icon={<IconShield />}
                title="Validation criteria"
                intro="Every candidate finding is checked against your quality bar before publishing, so noisy, speculative, or low-value issues never reach the pull request. Keep several bars on hand, but only one is applied."
                kind="validator"
                kindLabel="validator"
                createLabel="Create your own validation criteria"
                preamble={<ValidatorEffectivenessCard />}
                skills={validators?.map((s) => ({ ...s, on: s.active })) ?? null}
                onSelect={selectValidator}
            />

            <SkillDrawer />
            <ReviewDetailDrawer />
        </div>
    )
}
