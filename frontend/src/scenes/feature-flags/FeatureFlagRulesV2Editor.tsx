import {
    Announcements,
    DndContext,
    DragEndEvent,
    KeyboardSensor,
    PointerSensor,
    UniqueIdentifier,
    closestCenter,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment, Ref, useCallback, useId, useMemo, useRef } from 'react'

import { IconCalculator, IconCheckCircle, IconCode, IconLetter, IconPlusSmall, IconToggle } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonInput, LemonMenu, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Noun, groupsModel } from '~/models/groupsModel'
import { FeatureFlagRulesV2ReturnType } from '~/types'

import { RULES_V2_EDITABLE_RETURN_TYPES } from 'products/feature_flags/frontend/featureFlagConfigFormat'
import {
    RULES_V2_RULE_TYPES,
    RULES_V2_RULE_TYPE_META,
    RulesV2Connector,
    RulesV2DefaultStep,
    RulesV2FieldError,
    RulesV2RuleType,
    RulesV2RulesHeading,
    rulesV2RuleTypeMenuLabel,
} from 'products/feature_flags/frontend/RulesV2Flow'

import { FeatureFlagLogicProps, slugifyFeatureFlagKey } from './featureFlagLogic'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'
import { RulesV2RuleEditor } from './RulesV2RuleEditor'
import { RulesV2ValueInput } from './RulesV2ValueInput'

const RETURN_TYPE_META: Record<
    FeatureFlagRulesV2ReturnType,
    { label: string; description: string; icon: JSX.Element }
> = {
    boolean: {
        label: 'Boolean',
        description: 'Serves true or false. For releases, kill switches and simple tests.',
        icon: <IconToggle />,
    },
    string: {
        label: 'String',
        description: 'Serves a text value, such as a variant name or a config key.',
        icon: <IconLetter />,
    },
    number: {
        label: 'Number',
        description: 'Serves a number, such as a limit, a timeout or a price.',
        icon: <IconCalculator />,
    },
    object: {
        label: 'JSON object',
        description: 'Serves a JSON object, such as remote config or settings for a variant.',
        icon: <IconCode />,
    },
}

function ReturnTypePicker({
    value,
    onChange,
    disabledReason,
}: {
    value: FeatureFlagRulesV2ReturnType
    onChange: (returnType: FeatureFlagRulesV2ReturnType) => void
    disabledReason?: string
}): JSX.Element {
    const types = RULES_V2_EDITABLE_RETURN_TYPES
    // Arrow keys move the selection, as in any radio group.
    const onKeyDown = (event: React.KeyboardEvent): void => {
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
        if (!step || disabledReason) {
            return
        }
        event.preventDefault()
        const next = types[(types.indexOf(value) + step + types.length) % types.length]
        onChange(next)
        event.currentTarget.querySelector<HTMLElement>(`[data-return-type="${next}"]`)?.focus()
    }
    return (
        <div
            className="grid grid-cols-1 sm:grid-cols-2 gap-2"
            role="radiogroup"
            aria-label="Value type"
            onKeyDown={onKeyDown}
            data-attr="rules-v2-return-type"
        >
            {types.map((returnType) => {
                const meta = RETURN_TYPE_META[returnType]
                const selected = value === returnType
                const disabled = !!disabledReason && !selected
                return (
                    <Tooltip key={returnType} title={disabled ? disabledReason : undefined}>
                        <button
                            type="button"
                            role="radio"
                            aria-checked={selected}
                            // aria-disabled rather than disabled, so the tooltip with the reason still shows.
                            aria-disabled={disabled}
                            tabIndex={selected ? 0 : -1}
                            data-return-type={returnType}
                            onClick={() => !disabledReason && onChange(returnType)}
                            className={clsx(
                                'text-left rounded border p-2.5 flex flex-col gap-1 transition-colors bg-surface-primary',
                                selected
                                    ? 'border-accent ring-1 ring-accent'
                                    : disabledReason
                                      ? 'opacity-50 cursor-not-allowed'
                                      : 'hover:border-secondary cursor-pointer'
                            )}
                            data-attr={`rules-v2-return-type-${returnType}`}
                        >
                            <span className="flex items-center gap-1.5 font-semibold">
                                <span className="text-base flex">{meta.icon}</span>
                                {meta.label}
                                {selected && <IconCheckCircle className="ml-auto text-accent text-base" />}
                            </span>
                            <span className="text-xs text-secondary">{meta.description}</span>
                        </button>
                    </Tooltip>
                )
            })}
        </div>
    )
}

function AddRule({
    onAdd,
    empty,
    subjects,
    buttonRef,
}: {
    onAdd: (ruleType: RulesV2RuleType) => void
    empty: boolean
    subjects: Noun
    buttonRef: Ref<HTMLButtonElement>
}): JSX.Element {
    if (empty) {
        return (
            <div className="rounded border border-dashed p-4 flex flex-col gap-3" data-attr="rules-v2-empty-rules">
                <div className="flex flex-col">
                    <span className="font-semibold">Add your first rule</span>
                    <span className="text-xs text-secondary">
                        Until you add a rule, all {subjects.plural} get the default value below.
                    </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    {RULES_V2_RULE_TYPES.map((ruleType, index) => {
                        const meta = RULES_V2_RULE_TYPE_META[ruleType]
                        return (
                            <button
                                key={ruleType}
                                ref={index === 0 ? buttonRef : undefined}
                                type="button"
                                onClick={() => onAdd(ruleType)}
                                className="text-left rounded border bg-surface-primary p-3 flex flex-col gap-1 cursor-pointer hover:border-accent transition-colors"
                                data-attr={`rules-v2-add-rule-${ruleType}`}
                            >
                                <span className="flex items-center gap-1.5 font-semibold">
                                    <span className="text-base flex text-secondary">{meta.icon}</span>
                                    {meta.label}
                                </span>
                                <span className="text-xs text-secondary">{meta.description}</span>
                            </button>
                        )
                    })}
                </div>
            </div>
        )
    }
    return (
        <LemonMenu
            placement="bottom-start"
            items={RULES_V2_RULE_TYPES.map((ruleType) => ({
                label: rulesV2RuleTypeMenuLabel(ruleType),
                icon: RULES_V2_RULE_TYPE_META[ruleType].icon,
                onClick: () => onAdd(ruleType),
                'data-attr': `rules-v2-add-rule-${ruleType}`,
            }))}
        >
            <LemonButton
                ref={buttonRef}
                type="secondary"
                icon={<IconPlusSmall />}
                fullWidth
                center
                className="border-dashed"
                data-attr="rules-v2-add-rule"
            >
                Add rule
            </LemonButton>
        </LemonMenu>
    )
}

export function FeatureFlagRulesV2Editor({ id }: FeatureFlagLogicProps): JSX.Element {
    const logic = featureFlagRulesV2EditorLogic({ id })
    const {
        draft,
        rules,
        ruleKeys,
        shadowingRules,
        featureFlag,
        saving,
        saveError,
        saveDisabledReason,
        fieldError,
        hasUnsavedChanges,
    } = useValues(logic)
    const { setDraft, setConfig, setReturnType, addRule, moveRule, saveRulesV2Flag, editFeatureFlag } =
        useActions(logic)
    const { aggregationLabel } = useValues(groupsModel)
    const isNew = id === 'new'
    const keyInputId = useId()
    const descriptionInputId = useId()
    const returnType = draft.config.return_type
    const groupTypeIndex = draft.config.aggregation_group_type_index
    const subjects = useMemo(() => aggregationLabel(groupTypeIndex, true), [aggregationLabel, groupTypeIndex])
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const addRuleRef = useRef<HTMLButtonElement | null>(null)
    // A deleted rule's card and its focused menu button unmount, so focus moves to adding a rule.
    const focusAddRule = useCallback((): void => {
        setTimeout(() => addRuleRef.current?.focus())
    }, [])
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )
    // dnd-kit would read out its internal ids; users know rules by their number.
    const ruleNumber = (id: UniqueIdentifier | undefined): number => ruleKeys.indexOf(Number(id)) + 1
    const dragAnnouncements: Announcements = {
        onDragStart: ({ active }) => `Picked up rule ${ruleNumber(active.id)}.`,
        onDragOver: ({ active, over }) =>
            over ? `Rule ${ruleNumber(active.id)} is over position ${ruleNumber(over.id)}.` : undefined,
        onDragEnd: ({ active, over }) =>
            over
                ? `Rule ${ruleNumber(active.id)} moved to position ${ruleNumber(over.id)}.`
                : `Rule ${ruleNumber(active.id)} dropped.`,
        onDragCancel: ({ active }) => `Moving rule ${ruleNumber(active.id)} was cancelled.`,
    }
    const onDragEnd = ({ active, over }: DragEndEvent): void => {
        if (over && active.id !== over.id) {
            moveRule(ruleKeys.indexOf(Number(active.id)), ruleKeys.indexOf(Number(over.id)))
        }
    }
    const cancel = (): void => {
        if (isNew) {
            // Leaving the page asks before it discards a dirty draft.
            router.actions.push(urls.featureFlags())
        } else if (hasUnsavedChanges) {
            LemonDialog.open({
                title: 'Discard your changes?',
                description: 'Your edits to this flag will be lost.',
                primaryButton: { children: 'Discard changes', status: 'danger', onClick: () => editFeatureFlag(false) },
                secondaryButton: { children: 'Keep editing' },
            })
        } else {
            editFeatureFlag(false)
        }
    }

    return (
        <div className="flex flex-col gap-4 pb-16" data-attr="feature-flag-rules-v2-editor">
            <SceneTitleSection
                name={draft.key || (isNew ? 'New rules v2 flag' : featureFlag.key)}
                resourceType={{ type: !isNew && featureFlag.active ? 'feature_flag' : 'feature_flag_off' }}
                actions={
                    todayRailNav ? (
                        <>
                            <Button variant="outline" data-attr="cancel-rules-v2-flag" onClick={cancel}>
                                Cancel
                            </Button>
                            <Button
                                variant="primary"
                                data-attr="save-rules-v2-flag"
                                loading={saving}
                                disabledReason={saveDisabledReason}
                                onClick={saveRulesV2Flag}
                            >
                                {isNew ? 'Create flag' : 'Save'}
                            </Button>
                        </>
                    ) : (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                data-attr="cancel-rules-v2-flag"
                                onClick={cancel}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                data-attr="save-rules-v2-flag"
                                loading={saving}
                                disabledReason={saveDisabledReason}
                                onClick={saveRulesV2Flag}
                            >
                                {isNew ? 'Create flag' : 'Save'}
                            </LemonButton>
                        </>
                    )
                }
            />
            <SceneContent>
                {saveError && saveError.field === null && (
                    <LemonBanner type="error" data-attr="rules-v2-save-error">
                        {saveError.message}
                    </LemonBanner>
                )}
                <div className="flex gap-4 flex-wrap items-start">
                    <div className="flex-1 min-w-[20rem] max-w-[32rem] flex flex-col gap-4">
                        <div className="rounded border p-3 bg-surface-primary flex flex-col gap-3">
                            <LemonField.Pure
                                label="Flag key"
                                htmlFor={keyInputId}
                                error={fieldError('key')}
                                help={
                                    !isNew && draft.key !== featureFlag.key
                                        ? 'Changing the key breaks every SDK call that uses the old one.'
                                        : 'The key your code passes to the SDK. Letters, numbers, hyphens and underscores.'
                                }
                            >
                                <LemonInput
                                    id={keyInputId}
                                    value={draft.key}
                                    onChange={(key) => setDraft({ key: slugifyFeatureFlagKey(key) })}
                                    data-attr="rules-v2-flag-key"
                                    className="ph-ignore-input font-mono"
                                    autoComplete="off"
                                    autoFocus={isNew}
                                    spellCheck={false}
                                    placeholder="e.g. new-checkout"
                                />
                            </LemonField.Pure>
                            <LemonField.Pure
                                label="Description"
                                htmlFor={descriptionInputId}
                                showOptional
                                error={fieldError('name')}
                            >
                                <LemonTextArea
                                    id={descriptionInputId}
                                    value={draft.name}
                                    onChange={(name) => setDraft({ name })}
                                    placeholder="What does this flag control?"
                                    minRows={2}
                                    className="ph-ignore-input"
                                />
                            </LemonField.Pure>
                            <LemonField.Pure label="Tags" showOptional error={fieldError('tags')}>
                                <ObjectTags
                                    tags={draft.tags}
                                    onChange={(tags) => setDraft({ tags })}
                                    saving={saving}
                                    data-attr="rules-v2-flag-tags"
                                />
                            </LemonField.Pure>
                        </div>
                        <div className="rounded border p-3 bg-surface-primary flex flex-col gap-2">
                            <div className="flex flex-col">
                                <span className="font-semibold">Value type</span>
                                <span className="text-xs text-secondary">
                                    {isNew
                                        ? 'What the flag returns. You cannot change it after the flag is created.'
                                        : 'What the flag returns. It is fixed once the flag exists.'}
                                </span>
                            </div>
                            <ReturnTypePicker
                                value={returnType}
                                onChange={setReturnType}
                                disabledReason={
                                    isNew ? undefined : 'The value type cannot be changed after the flag is created.'
                                }
                            />
                            <RulesV2FieldError error={fieldError('filters.return_type')} />
                        </div>
                        <div className="rounded border border-dashed p-3 flex flex-col gap-2 text-xs text-secondary">
                            <span className="font-semibold text-default text-sm">How rules work</span>
                            <ol className="m-0 pl-4 flex flex-col gap-1 list-decimal">
                                <li>Rules are checked from the top. Drag a rule to change its place.</li>
                                <li>
                                    A rule first checks its conditions. A {subjects.singular} who doesn't match moves on
                                    to the next rule.
                                </li>
                                <li>
                                    A rollout or experiment then picks a share of the matching {subjects.plural}. You
                                    choose whether the rest move on or get the default value.
                                </li>
                                <li>The first rule that serves a value wins. Nobody is served twice.</li>
                            </ol>
                            {isNew && <span>New flags are created disabled. Enable the flag on its page.</span>}
                        </div>
                    </div>
                    <div className="flex-[2] min-w-[30rem] flex flex-col" data-attr="rules-v2-rules">
                        <RulesV2RulesHeading subjects={subjects} className="mb-2" />
                        <DndContext
                            accessibility={{ announcements: dragAnnouncements }}
                            sensors={sensors}
                            collisionDetection={closestCenter}
                            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                            onDragEnd={onDragEnd}
                        >
                            <SortableContext items={ruleKeys} strategy={verticalListSortingStrategy}>
                                <div className="flex flex-col">
                                    {rules.map((rule, index) => (
                                        <Fragment key={ruleKeys[index]}>
                                            <RulesV2RuleEditor
                                                ruleKey={ruleKeys[index]}
                                                id={id}
                                                index={index}
                                                rule={rule}
                                                ruleCount={rules.length}
                                                returnType={returnType}
                                                defaultValue={draft.config.default_value}
                                                subjects={subjects}
                                                groupTypeIndex={groupTypeIndex ?? null}
                                                shadowedBy={shadowingRules[index]}
                                                onRemoved={focusAddRule}
                                            />
                                            <RulesV2Connector />
                                        </Fragment>
                                    ))}
                                </div>
                            </SortableContext>
                        </DndContext>
                        <AddRule
                            onAdd={addRule}
                            empty={rules.length === 0}
                            subjects={subjects}
                            buttonRef={addRuleRef}
                        />
                        <RulesV2Connector />
                        <RulesV2DefaultStep subjects={subjects} rules={rules}>
                            <div className="flex flex-col gap-1">
                                <RulesV2ValueInput
                                    aria-label="Default value"
                                    returnType={returnType}
                                    value={draft.config.default_value}
                                    onChange={(default_value) => {
                                        // A click on the selected true or false reports it again, which is not an edit.
                                        if (!objectsEqual(default_value, draft.config.default_value)) {
                                            setConfig({ default_value })
                                        }
                                    }}
                                    nullable
                                    className="w-56"
                                    data-attr="rules-v2-default-value"
                                />
                                <RulesV2FieldError error={fieldError('filters.default_value')} />
                            </div>
                        </RulesV2DefaultStep>
                    </div>
                </div>
            </SceneContent>
        </div>
    )
}
