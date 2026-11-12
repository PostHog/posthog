import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ResourceTagFilter } from '../components/ResourceTagFilter'
import { defaultCompositeExpression } from './compositeFormulaDefaults'
import { compositeInputsLogic } from './compositeInputsLogic'
import { buildCompositionFromDraft, buildConfigFromDraft, type ScoreDefinitionDraft } from './scoreDefinitionModalUtils'

export interface CompositeScorerFormProps {
    draft: ScoreDefinitionDraft
    disabled: boolean
    setDraftField: (field: keyof ScoreDefinitionDraft, value: ScoreDefinitionDraft[keyof ScoreDefinitionDraft]) => void
}

export function CompositeScorerForm({ draft, disabled, setDraftField }: CompositeScorerFormProps): JSX.Element {
    const id = useId()
    const logic = compositeInputsLogic({
        id,
        initialDefinitionIds: [...new Set(draft.inputs.map((input) => input.definition_id))],
    })
    const {
        options,
        optionsLoading,
        optionsError,
        search,
        tagFilters,
        versions,
        versionsLoadingById,
        versionsError,
        validation,
        validationLoading,
    } = useValues(logic)
    const { setSearch, setTagFilters, loadOptions, loadVersions, validateFormula } = useActions(logic)
    const updateInput = (index: number, patch: Partial<ScoreDefinitionDraft['inputs'][number]>): void =>
        setDraftField(
            'inputs',
            draft.inputs.map((input, position) => (position === index ? { ...input, ...patch } : input))
        )
    const suggested = defaultCompositeExpression(draft)
    const checked =
        validation?.fingerprint ===
        JSON.stringify({
            kind: draft.kind,
            composition: buildCompositionFromDraft(draft),
            config: buildConfigFromDraft(draft),
        })
            ? validation
            : null

    return (
        <section className="flex flex-col gap-4 @container/composite-form" aria-labelledby={`${id}-heading`}>
            <h3 id={`${id}-heading`} className="mb-0">
                Composite calculation
            </h3>
            {draft.inputs.map((input, index) => {
                const loadedLatest = versions[input.definition_id]?.results[0]
                const latest =
                    loadedLatest && loadedLatest.version >= (input.latest_version || 0)
                        ? loadedLatest
                        : { id: input.latest_version_id, version: input.latest_version, config: undefined }
                return (
                    <div key={index} className="border rounded p-3 space-y-3">
                        <div className="flex flex-wrap justify-between gap-2">
                            <Link
                                to={urls.aiObservabilityScorer(input.definition_id)}
                                target="_blank"
                                targetBlankIcon
                                tooltip="Open in a new tab"
                                className="min-w-0 break-words"
                            >
                                {input.name}
                            </Link>
                            <LemonButton
                                size="xsmall"
                                status="danger"
                                disabledReason={disabled ? 'Saving scorer' : undefined}
                                data-attr="aio-composite-remove-input"
                                onClick={() =>
                                    setDraftField(
                                        'inputs',
                                        draft.inputs.filter((_, position) => position !== index)
                                    )
                                }
                            >
                                Remove
                            </LemonButton>
                        </div>
                        <div className="grid gap-3 @min-[32rem]/composite-form:grid-cols-2">
                            <LemonField.Pure label="Formula name" htmlFor={`${id}-alias-${index}`}>
                                <LemonInput
                                    id={`${id}-alias-${index}`}
                                    value={input.alias}
                                    onChange={(alias) => updateInput(index, { alias })}
                                    disabled={disabled}
                                    maxLength={32}
                                    data-attr="aio-composite-input-alias"
                                />
                            </LemonField.Pure>
                            <LemonField.Pure label="Version">
                                <div className="flex flex-wrap gap-2 items-center">
                                    <LemonSelect
                                        value={input.scorer_version_id}
                                        data-attr="aio-composite-input-version"
                                        disabledReason={
                                            disabled
                                                ? 'Saving scorer'
                                                : versionsLoadingById[input.definition_id]
                                                  ? 'Loading versions'
                                                  : undefined
                                        }
                                        options={[
                                            { value: input.scorer_version_id, label: `Version ${input.version}` },
                                            ...(versions[input.definition_id]?.results || [])
                                                .filter((version) => version.id !== input.scorer_version_id)
                                                .map((version) => ({
                                                    value: version.id,
                                                    label: `Version ${version.version}`,
                                                })),
                                        ]}
                                        onChange={(value) => {
                                            const version = versions[input.definition_id]?.results.find(
                                                (version) => version.id === value
                                            )
                                            if (version) {
                                                updateInput(index, {
                                                    scorer_version_id: version.id,
                                                    version: version.version,
                                                    config: version.config,
                                                })
                                            }
                                        }}
                                    />
                                    <LemonButton
                                        size="small"
                                        icon={<IconRefresh />}
                                        aria-label={`Refresh versions for ${input.name}`}
                                        tooltip="Refresh versions"
                                        loading={versionsLoadingById[input.definition_id]}
                                        disabledReason={disabled ? 'Saving scorer' : undefined}
                                        data-attr="aio-composite-refresh-versions"
                                        onClick={() => loadVersions(input.definition_id)}
                                    />
                                    {versions[input.definition_id]?.next_cursor && (
                                        <LemonButton
                                            size="small"
                                            loading={versionsLoadingById[input.definition_id]}
                                            disabledReason={disabled ? 'Saving scorer' : undefined}
                                            data-attr="aio-composite-more-versions"
                                            onClick={() =>
                                                loadVersions(
                                                    input.definition_id,
                                                    versions[input.definition_id].next_cursor!
                                                )
                                            }
                                        >
                                            More versions
                                        </LemonButton>
                                    )}
                                </div>
                            </LemonField.Pure>
                        </div>
                        {latest.id && input.scorer_version_id !== latest.id && (
                            <LemonBanner
                                type="warning"
                                action={{
                                    children: `Use version ${latest.version}`,
                                    disabledReason: disabled
                                        ? 'Saving scorer'
                                        : latest.config === undefined
                                          ? 'Load this version before using it'
                                          : undefined,
                                    'data-attr': 'aio-composite-upgrade-input',
                                    onClick: () =>
                                        updateInput(index, {
                                            scorer_version_id: latest.id!,
                                            version: latest.version!,
                                            config: latest.config,
                                        }),
                                }}
                            >{`${input.name} has a newer version.`}</LemonBanner>
                        )}
                    </div>
                )
            })}
            {versionsError && (
                <LemonBanner type="error">
                    Could not load input versions. Use the refresh button to try again.
                </LemonBanner>
            )}
            {draft.inputs.length < 16 && (
                <LemonField.Pure label="Add input scorer">
                    <div className="space-y-2 w-full">
                        <div className="flex flex-wrap gap-2 items-center">
                            <LemonInput
                                type="search"
                                size="small"
                                className="w-48 max-w-full"
                                value={search}
                                onChange={setSearch}
                                onPressEnter={(event) => event.preventDefault()}
                                placeholder="Search scorers"
                                disabled={disabled}
                                aria-label="Search input scorers"
                                data-attr="aio-composite-input-search"
                            />
                            <ResourceTagFilter size="small" filters={tagFilters} onChange={setTagFilters} />
                        </div>
                        {optionsError ? (
                            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadOptions }}>
                                Could not load input scorers.
                            </LemonBanner>
                        ) : (
                            <LemonSelect
                                value={null}
                                placeholder={optionsLoading ? 'Loading scorers…' : 'Choose a scorer'}
                                fullWidth
                                data-attr="aio-composite-add-input"
                                disabledReason={
                                    disabled ? 'Saving scorer' : optionsLoading ? 'Loading scorers' : undefined
                                }
                                options={(options?.results || [])
                                    .filter(
                                        (scorer) =>
                                            scorer.current_version_id &&
                                            !draft.inputs.some((input) => input.definition_id === scorer.id)
                                    )
                                    .map((scorer) => ({ value: scorer.id, label: `${scorer.name} (${scorer.kind})` }))}
                                onChange={(value) => {
                                    const scorer = options?.results.find((scorer) => scorer.id === value)
                                    if (!scorer?.current_version_id) {
                                        return
                                    }
                                    let suffix = 1
                                    while (draft.inputs.some((input) => input.alias === `score${suffix}`)) {
                                        suffix++
                                    }
                                    setDraftField('inputs', [
                                        ...draft.inputs,
                                        {
                                            alias: `score${suffix}`,
                                            scorer_version_id: scorer.current_version_id,
                                            definition_id: scorer.id,
                                            name: scorer.name,
                                            kind: scorer.kind,
                                            version: scorer.current_version,
                                            latest_version: scorer.current_version,
                                            latest_version_id: scorer.current_version_id,
                                            config: scorer.config,
                                        },
                                    ])
                                    loadVersions(scorer.id)
                                }}
                            />
                        )}
                        {options && !optionsLoading && !options.results.length && (
                            <p className="text-muted mb-0">No matching scorers. Try another search or tag.</p>
                        )}
                        {options && options.count > options.results.length && (
                            <p className="text-muted mb-0">Showing 50 matches. Narrow your search or filter by tags.</p>
                        )}
                    </div>
                </LemonField.Pure>
            )}
            <div className="border-t pt-4 flex flex-col gap-3">
                <LemonField.Pure label="Formula" htmlFor={`${id}-expression`}>
                    <LemonTextArea
                        id={`${id}-expression`}
                        value={draft.expression}
                        onChange={(value) => setDraftField('expression', value)}
                        disabled={disabled}
                        maxLength={1024}
                        className="font-mono"
                        data-attr="aio-composite-expression"
                        placeholder={
                            draft.inputs.length
                                ? 'Write a formula using the input names above'
                                : 'Add an input scorer to start'
                        }
                    />
                </LemonField.Pure>
                {!draft.expressionIsCustom && draft.inputs.length > 0 && (
                    <p className="text-sm text-muted mb-0">
                        {suggested === null
                            ? 'No default fits these scoring rules and formula limits. Write a formula, or adjust the inputs and output rules.'
                            : draft.kind === 'numeric'
                              ? 'Averages numeric values. Passing Boolean and categorical inputs count as 1; failing inputs count as 0.'
                              : draft.kind === 'boolean'
                                ? `${draft.booleanPassing === 'false' ? 'False' : 'True'} when every input passes its rule.`
                                : 'Returns passing categories when all inputs pass; otherwise includes a failing category.'}
                    </p>
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton
                        size="small"
                        type="secondary"
                        loading={validationLoading}
                        data-attr="aio-composite-validate-formula"
                        disabledReason={
                            disabled
                                ? 'Saving scorer'
                                : !draft.inputs.length || !draft.expression.trim()
                                  ? 'Add inputs and a formula first'
                                  : undefined
                        }
                        onClick={() => validateFormula(draft)}
                    >
                        Validate formula
                    </LemonButton>
                    {draft.expressionIsCustom && suggested && (
                        <LemonButton
                            size="small"
                            data-attr="aio-composite-use-default"
                            disabledReason={disabled ? 'Saving scorer' : undefined}
                            onClick={() => setDraftField('expressionIsCustom', false)}
                        >
                            Use default formula
                        </LemonButton>
                    )}
                </div>
                {checked && (
                    <LemonBanner type={checked.error ? 'error' : 'success'}>
                        {checked.error ||
                            'Formula and output configuration are valid. Values are checked when results arrive.'}
                    </LemonBanner>
                )}
            </div>
            <LemonCollapse
                embedded
                panels={[
                    {
                        key: 'reference',
                        header: 'Formula examples',
                        dataAttr: 'aio-composite-formula-examples',
                        content: (
                            <LemonTable
                                size="small"
                                rowKey="name"
                                dataSource={[
                                    { name: 'Weighted average', formula: '(2 * score1 + score2) / 3' },
                                    { name: 'Both Boolean values are true', formula: 'score1 and score2' },
                                    { name: 'True as 1, false as 0', formula: 'number(score1)' },
                                    { name: 'Check a category', formula: '"good" in score1' },
                                    { name: 'Choose a category', formula: '"good" if score1 else "bad"' },
                                ]}
                                columns={[
                                    { title: 'Use case', dataIndex: 'name' },
                                    {
                                        title: 'Example',
                                        dataIndex: 'formula',
                                        render: (formula) => (
                                            <code className="whitespace-pre-wrap break-words">{formula}</code>
                                        ),
                                    },
                                ]}
                            />
                        ),
                    },
                ]}
            />
        </section>
    )
}
