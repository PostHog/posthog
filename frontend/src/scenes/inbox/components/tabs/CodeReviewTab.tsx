import { useActions, useValues } from 'kea'

import { IconExternal, IconGithub, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonSlider, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer'

import type { UrgencyThresholdEnumApi } from 'products/review_hog/frontend/generated/api.schemas'

import { ReviewSkillKind, reviewHogSettingsLogic } from '../../logics/reviewHogSettingsLogic'

const SKILLS_EDITOR_URL = '/skills/review-hog'

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
    title,
    pill,
    children,
}: {
    title: string
    pill?: JSX.Element
    children: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2.5">
                <h3 className="m-0 text-base font-semibold">{title}</h3>
                {pill}
            </div>
            <p className="m-0 max-w-160 text-xs text-secondary">{children}</p>
        </div>
    )
}

function PipelineSection(): JSX.Element {
    return (
        <section className="flex flex-col gap-4">
            <SectionHeader title="How we review your PRs">
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

function ReviewHogMark({ className }: { className?: string }): JSX.Element {
    // The three-bar PostHog slash mark, matching the Inbox onboarding hero.
    return (
        <div className={`flex gap-1 ${className ?? ''}`} aria-hidden>
            {[0, 1, 2].map((i) => (
                <div key={i} className="h-5 w-1.5 bg-default" style={{ transform: 'skewX(-16deg)' }} />
            ))}
        </div>
    )
}

function TriggersSection(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)

    const switchDisabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined

    return (
        <section className="flex flex-col gap-4">
            <SectionHeader title="What gets reviewed">
                Choose which pull requests ReviewHog picks up automatically.
            </SectionHeader>
            <LemonCard hoverEffect={false} className="divide-y divide-primary p-0">
                <div className="flex items-center gap-4 p-4">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded border border-primary bg-primary">
                        <ReviewHogMark />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold">Review all your Inbox PRs</div>
                        <div className="text-xs text-secondary">
                            Coming soon — this switch doesn't trigger reviews yet. Once live, any pull request opened by
                            PostHog agents from your Inbox will be reviewed automatically.
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
                                className="font-mono text-xs text-warning"
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
        <section className="flex flex-col gap-4">
            <SectionHeader title="Urgency threshold">
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
    highlightActive,
    onToggle,
}: {
    skill: SkillCardData
    onLabel: string
    offLabel: string
    /** Single-active lists mark the active card with an accent border. */
    highlightActive?: boolean
    onToggle: (checked: boolean) => void
}): JSX.Element {
    const { savingSkillNames } = useValues(reviewHogSettingsLogic)
    const { viewSkill } = useActions(reviewHogSettingsLogic)
    const title = prettifySkillName(skill.skill_name)

    return (
        <LemonCard hoverEffect={false} className={`p-4 ${highlightActive && skill.on ? 'border-warning' : ''}`}>
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
                        <Link onClick={() => viewSkill({ title, body: skill.body })}>View skill</Link>
                        <span className="text-tertiary">·</span>
                        <Link to={SKILLS_EDITOR_URL} target="_blank" className="inline-flex items-center gap-0.5">
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

function PerspectivesSection(): JSX.Element {
    const { perspectives } = useValues(reviewHogSettingsLogic)
    const { togglePerspective } = useActions(reviewHogSettingsLogic)

    return (
        <section className="flex flex-col gap-4">
            <SectionHeader
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
    title,
    intro,
    kind,
    kindLabel,
    createLabel,
    skills,
    onSelect,
}: {
    title: string
    intro: string
    kind: ReviewSkillKind
    kindLabel: string
    createLabel: string
    skills: SkillCardData[] | null
    onSelect: (skillName: string) => void
}): JSX.Element {
    const { blockSingleActiveDeactivation } = useActions(reviewHogSettingsLogic)

    return (
        <section className="flex flex-col gap-4">
            <SectionHeader
                title={title}
                pill={
                    <LemonTag type="warning" size="small">
                        One active at a time
                    </LemonTag>
                }
            >
                {intro}
            </SectionHeader>
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
                            highlightActive
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
                <LemonButton type="secondary" to={SKILLS_EDITOR_URL} targetBlank icon={<IconExternal />}>
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
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-12 px-6 pb-30 pt-11">
            <section className="flex flex-col gap-3">
                <ReviewHogMark className="mb-1" />
                <h2 className="m-0 text-2xl font-bold" style={{ textWrap: 'balance' }}>
                    ReviewHog reviews pull requests before humans do
                </h2>
                <p className="m-0 max-w-155 text-sm text-secondary">
                    Specialist review perspectives read your changed code in parallel, a blind-spot sweep catches what
                    they missed, and only validated findings get published back to the pull request.
                </p>
            </section>

            {initialLoadFailed && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadAll() }}>
                    Some ReviewHog settings failed to load.
                </LemonBanner>
            )}

            <PipelineSection />
            <TriggersSection />
            <UrgencySection />
            <PerspectivesSection />
            <SingleActiveSection
                title="Blind-spot check"
                intro="After the enabled perspectives finish, ReviewHog runs one more sweep over each chunk — it sees what they found and hunts for real issues they all missed. Add as many sweeps as you like, but only one runs."
                kind="blind_spots"
                kindLabel="blind-spot check"
                createLabel="Create your own blind-spot check"
                skills={blindSpots?.map((s) => ({ ...s, on: s.active })) ?? null}
                onSelect={selectBlindSpots}
            />
            <SingleActiveSection
                title="Validation criteria"
                intro="Every candidate finding is checked against your quality bar before publishing, so noisy, speculative, or low-value issues never reach the pull request. Keep several bars on hand, but only one is applied."
                kind="validator"
                kindLabel="validator"
                createLabel="Create your own validation criteria"
                skills={validators?.map((s) => ({ ...s, on: s.active })) ?? null}
                onSelect={selectValidator}
            />

            <SkillDrawer />
        </div>
    )
}
