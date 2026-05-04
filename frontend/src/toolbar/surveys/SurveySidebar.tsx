import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArchive, IconEllipsis, IconExternal, IconPlus, IconRocket, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { joinWithUiHost } from '~/toolbar/utils'

import { SIDEBAR_WIDTH } from './constants'
import { SurveyLivePreview } from './SurveyLivePreview'
import {
    FREQUENCY_OPTIONS,
    getSurveyStatus,
    type QuickSurveyQuestionType,
    surveysToolbarLogic,
} from './surveysToolbarLogic'

const SIDEBAR_TRANSITION_MS = 200

const QUESTION_TYPE_OPTIONS = [
    { value: 'open' as const, label: 'Open text' },
    { value: 'rating' as const, label: 'Rating scale' },
    { value: 'single_choice' as const, label: 'Single choice' },
]

function QuestionSection(): JSX.Element {
    const { quickForm } = useValues(surveysToolbarLogic)
    const { setFormField } = useActions(surveysToolbarLogic)

    return (
        <section>
            <h3 className="text-xs font-semibold text-muted-3000 uppercase tracking-wide mb-3">Question</h3>
            <div className="space-y-3">
                <div>
                    <label className="text-xs font-medium text-muted mb-0.5 block">Name</label>
                    <LemonInput
                        autoFocus
                        placeholder="e.g. Feedback on checkout"
                        fullWidth
                        size="small"
                        value={quickForm.name}
                        onChange={(v) => setFormField('name', v)}
                    />
                </div>

                <div>
                    <label className="text-xs font-medium text-muted mb-0.5 block">Question type</label>
                    <LemonSelect
                        fullWidth
                        size="small"
                        options={QUESTION_TYPE_OPTIONS}
                        value={quickForm.questionType}
                        onChange={(v) => setFormField('questionType', v as QuickSurveyQuestionType)}
                    />
                </div>

                <div>
                    <label className="text-xs font-medium text-muted mb-0.5 block">Question</label>
                    <LemonTextArea
                        placeholder="What would you like to ask?"
                        value={quickForm.questionText}
                        onChange={(v) => setFormField('questionText', v)}
                        minRows={2}
                        maxRows={4}
                    />
                </div>

                {quickForm.questionType === 'rating' && (
                    <>
                        <div>
                            <label className="text-xs font-medium text-muted mb-0.5 block">Scale</label>
                            <LemonSelect
                                fullWidth
                                size="small"
                                options={[
                                    { value: 5, label: '1\u20135' },
                                    { value: 10, label: '1\u201310 (NPS)' },
                                ]}
                                value={quickForm.ratingScale}
                                onChange={(v) => setFormField('ratingScale', v)}
                            />
                        </div>
                        <div className="flex gap-2">
                            <div className="flex-1">
                                <label className="text-xs font-medium text-muted mb-0.5 block">Low label</label>
                                <LemonInput
                                    size="small"
                                    fullWidth
                                    value={quickForm.ratingLowerLabel}
                                    onChange={(v) => setFormField('ratingLowerLabel', v)}
                                />
                            </div>
                            <div className="flex-1">
                                <label className="text-xs font-medium text-muted mb-0.5 block">High label</label>
                                <LemonInput
                                    size="small"
                                    fullWidth
                                    value={quickForm.ratingUpperLabel}
                                    onChange={(v) => setFormField('ratingUpperLabel', v)}
                                />
                            </div>
                        </div>
                    </>
                )}

                {quickForm.questionType === 'single_choice' && (
                    <div>
                        <label className="text-xs font-medium text-muted mb-0.5 block">Choices</label>
                        <div className="space-y-1">
                            {quickForm.choices.map((choice, i) => (
                                <div key={i} className="flex gap-1 items-center">
                                    <LemonInput
                                        size="small"
                                        fullWidth
                                        placeholder={`Option ${i + 1}`}
                                        value={choice}
                                        onChange={(v) => {
                                            const newChoices = [...quickForm.choices]
                                            newChoices[i] = v
                                            setFormField('choices', newChoices)
                                        }}
                                    />
                                    {quickForm.choices.length > 2 && (
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconTrash />}
                                            onClick={() => {
                                                const newChoices = quickForm.choices.filter((_, j) => j !== i)
                                                setFormField('choices', newChoices)
                                            }}
                                        />
                                    )}
                                </div>
                            ))}
                            {quickForm.choices.length < 6 && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    icon={<IconPlus />}
                                    fullWidth
                                    onClick={() => setFormField('choices', [...quickForm.choices, ''])}
                                >
                                    Add option
                                </LemonButton>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </section>
    )
}

function WhereSection(): JSX.Element {
    const { quickForm } = useValues(surveysToolbarLogic)
    const { setFormField } = useActions(surveysToolbarLogic)

    return (
        <section>
            <h3 className="text-xs font-semibold text-muted-3000 uppercase tracking-wide mb-3">Where</h3>
            <div className="space-y-3">
                <div>
                    <p className="text-xs text-muted mb-2">Choose which pages will show this survey</p>
                    <LemonRadio
                        value={quickForm.targetingMode}
                        onChange={(v) => setFormField('targetingMode', v)}
                        options={[
                            {
                                value: 'all',
                                label: 'All pages',
                                description: 'Survey can appear anywhere on your site',
                            },
                            {
                                value: 'specific',
                                label: 'Specific pages',
                                description: 'Only show on pages matching a URL pattern',
                            },
                        ]}
                    />
                    {quickForm.targetingMode === 'specific' && (
                        <div className="mt-2 ml-6">
                            <LemonInput
                                size="small"
                                fullWidth
                                placeholder="/pricing"
                                value={quickForm.urlMatch}
                                onChange={(v) => setFormField('urlMatch', v)}
                            />
                            <span className="text-xs text-muted mt-0.5 block">
                                Auto-filled from current page. Uses &quot;contains&quot; matching.
                            </span>
                        </div>
                    )}
                </div>
            </div>
        </section>
    )
}

function WhenSection(): JSX.Element {
    const { quickForm } = useValues(surveysToolbarLogic)
    const { setFormField } = useActions(surveysToolbarLogic)

    return (
        <section>
            <h3 className="text-xs font-semibold text-muted-3000 uppercase tracking-wide mb-3">When</h3>
            <div className="space-y-3">
                <div>
                    <p className="text-xs text-muted mb-2">Choose when to show this survey</p>
                    <LemonRadio
                        value={quickForm.triggerMode}
                        onChange={(v) => setFormField('triggerMode', v)}
                        options={[
                            {
                                value: 'pageview',
                                label: 'On page load',
                                description: 'Shows when the user visits the page',
                            },
                            {
                                value: 'event',
                                label: 'When an event is captured',
                                description: 'Trigger the survey after a specific event',
                            },
                        ]}
                    />
                    {quickForm.triggerMode === 'event' && (
                        <div className="mt-2 ml-6">
                            <LemonInput
                                size="small"
                                fullWidth
                                placeholder="e.g. purchase_completed"
                                value={quickForm.triggerEventName}
                                onChange={(v) => setFormField('triggerEventName', v)}
                            />
                            <span className="text-xs text-muted mt-0.5 block">
                                Enter the event name that triggers this survey
                            </span>
                        </div>
                    )}
                </div>

                <div>
                    <p className="text-xs text-muted mb-2">How often can someone see this?</p>
                    <LemonSegmentedButton
                        value={quickForm.frequency}
                        onChange={(v) => setFormField('frequency', v)}
                        options={FREQUENCY_OPTIONS.map((opt) => ({
                            value: opt.value,
                            label: opt.label,
                        }))}
                        fullWidth
                        size="small"
                    />
                </div>

                <div>
                    <p className="text-xs font-medium text-muted mb-1">Delay before showing</p>
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="number"
                            min={0}
                            size="small"
                            value={quickForm.delaySeconds}
                            onChange={(val) => setFormField('delaySeconds', Number(val) || 0)}
                            className="w-20"
                        />
                        <span className="text-xs text-muted">seconds after conditions are met</span>
                    </div>
                </div>
            </div>
        </section>
    )
}

export function SurveySidebar(): JSX.Element | null {
    const { isCreating, isSubmitting, canProceed, editingSurveyId, allSurveys } = useValues(surveysToolbarLogic)
    const { cancelQuickCreate, submitQuickCreate, stopSurvey, resumeSurvey, archiveSurvey } =
        useActions(surveysToolbarLogic)
    const { uiHost } = useValues(toolbarConfigLogic)
    const editingSurvey = editingSurveyId ? allSurveys.find((s) => s.id === editingSurveyId) : null
    const isEditing = !!editingSurveyId
    const status = editingSurvey ? getSurveyStatus(editingSurvey) : null

    useEffect(() => {
        if (isCreating) {
            document.body.style.transition = `margin ${SIDEBAR_TRANSITION_MS}ms ease-out`
            document.body.style.marginRight = `${SIDEBAR_WIDTH}px`

            return () => {
                document.body.style.marginRight = ''
                document.body.style.transition = ''
            }
        }
    }, [isCreating])

    if (!isCreating) {
        return null
    }

    return (
        <>
            <SurveyLivePreview />
            <div
                className="flex flex-col"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'fixed',
                    top: 0,
                    right: 0,
                    bottom: 0,
                    width: SIDEBAR_WIDTH,
                    backgroundColor: 'var(--color-bg-3000)',
                    borderLeft: '1px solid var(--border-bold-3000)',
                    boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.4)',
                    zIndex: 2147483019,
                    pointerEvents: 'auto',
                    color: 'var(--text-3000)',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="px-4 pt-4 pb-3 border-b border-border-bold-3000 bg-bg-light">
                    {/* Title row — identity is dominant; status is a typographic signal, not a button */}
                    <div className="flex items-start justify-between gap-2 mb-3">
                        <div className="min-w-0 flex-1">
                            <h2 className="m-0 text-sm font-semibold leading-tight truncate">
                                {isEditing ? 'Edit survey' : 'New survey'}
                            </h2>
                            {isEditing && status && (
                                <p
                                    className={`text-xs font-medium m-0 mt-0.5 ${
                                        status === 'active'
                                            ? 'text-success-3000'
                                            : status === 'draft'
                                              ? 'text-warning'
                                              : 'text-muted'
                                    }`}
                                >
                                    {status === 'active'
                                        ? 'Live on your site'
                                        : status === 'draft'
                                          ? 'Draft — not yet launched'
                                          : 'Ended'}
                                </p>
                            )}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                            {isEditing && editingSurvey && (
                                <LemonMenu
                                    placement="bottom-end"
                                    items={[
                                        {
                                            label: 'Archive survey',
                                            icon: <IconArchive />,
                                            status: 'danger',
                                            onClick: () => {
                                                if (
                                                    window.confirm(
                                                        'Archive this survey? It will be hidden from the toolbar list. You can unarchive it from PostHog.'
                                                    )
                                                ) {
                                                    archiveSurvey(editingSurvey)
                                                }
                                            },
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        icon={<IconEllipsis />}
                                        tooltip="More actions"
                                    />
                                </LemonMenu>
                            )}
                            <button
                                type="button"
                                onClick={cancelQuickCreate}
                                aria-label="Close"
                                className="p-1 rounded border-none bg-transparent cursor-pointer text-muted-3000 hover:text-text-3000 flex items-center justify-center"
                            >
                                <IconX className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    {/* One primary action. Lifecycle toggle (Stop/Resume) sits beside it as a peer when relevant. */}
                    {isEditing && editingSurvey ? (
                        <div className="flex gap-2">
                            {status === 'draft' && (
                                <>
                                    <LemonButton
                                        type="tertiary"
                                        center
                                        className="flex-1"
                                        loading={isSubmitting}
                                        disabledReason={!canProceed ? 'Fill in the name and question' : undefined}
                                        onClick={() => submitQuickCreate(false)}
                                    >
                                        Save changes
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        center
                                        className="flex-1"
                                        icon={<IconRocket />}
                                        loading={isSubmitting}
                                        disabledReason={!canProceed ? 'Fill in the name and question' : undefined}
                                        onClick={() => submitQuickCreate(true)}
                                    >
                                        Launch
                                    </LemonButton>
                                </>
                            )}
                            {status === 'active' && (
                                <>
                                    <LemonButton
                                        type="tertiary"
                                        center
                                        className="flex-1"
                                        onClick={() => stopSurvey(editingSurvey)}
                                    >
                                        End survey
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        center
                                        className="flex-1"
                                        loading={isSubmitting}
                                        disabledReason={!canProceed ? 'Fill in the name and question' : undefined}
                                        onClick={() => submitQuickCreate(false)}
                                    >
                                        Save changes
                                    </LemonButton>
                                </>
                            )}
                            {status === 'complete' && (
                                <>
                                    <LemonButton
                                        type="tertiary"
                                        center
                                        className="flex-1"
                                        onClick={() => resumeSurvey(editingSurvey)}
                                    >
                                        Resume
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        center
                                        className="flex-1"
                                        loading={isSubmitting}
                                        disabledReason={!canProceed ? 'Fill in the name and question' : undefined}
                                        onClick={() => submitQuickCreate(false)}
                                    >
                                        Save changes
                                    </LemonButton>
                                </>
                            )}
                        </div>
                    ) : (
                        <div className="flex gap-2">
                            <LemonButton
                                type="tertiary"
                                center
                                className="flex-1"
                                loading={isSubmitting}
                                disabledReason={!canProceed ? 'Fill in the name and question' : undefined}
                                onClick={() => submitQuickCreate(false)}
                            >
                                Save draft
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                center
                                className="flex-1"
                                icon={<IconRocket />}
                                loading={isSubmitting}
                                disabledReason={!canProceed ? 'Fill in the name and question' : undefined}
                                onClick={() => submitQuickCreate(true)}
                            >
                                Launch
                            </LemonButton>
                        </div>
                    )}
                </div>

                {/* Scrollable form body */}
                <div className="flex-1 overflow-y-auto p-4 space-y-5">
                    {/* Compact info strip — quiet caption, doesn't compete with the form. */}
                    <p className="text-xs text-muted m-0 leading-snug">
                        Quick form for single-question surveys. Need branching or multiple questions?{' '}
                        <Link to={joinWithUiHost(uiHost, urls.surveys())} target="_blank" subtle>
                            Open in PostHog <IconExternal className="inline w-3 h-3" />
                        </Link>
                    </p>
                    <QuestionSection />
                    <div className="border-t border-border-bold-3000" />
                    <WhereSection />
                    <div className="border-t border-border-bold-3000" />
                    <WhenSection />
                </div>
            </div>
        </>
    )
}
