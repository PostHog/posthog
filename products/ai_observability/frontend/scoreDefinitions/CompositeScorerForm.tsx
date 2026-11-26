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
import type { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ResourceTagFilter } from '../components/ResourceTagFilter'
import { ExperimentScoreResult } from '../offline-evaluations/ExperimentScoreResult'
import { defaultCompositeExpression } from './compositeFormulaDefaults'
import { compositeInputsLogic } from './compositeInputsLogic'
import { getCategoricalConfig, getNumericConfig } from './scoreDefinitionConfigUtils'
import { buildCompositionFromDraft, buildConfigFromDraft, type ScoreDefinitionDraft } from './scoreDefinitionModalUtils'

export interface CompositeScorerFormProps {
    experimentId?: string
    draft: ScoreDefinitionDraft
    disabled: boolean
    setDraftField: (field: keyof ScoreDefinitionDraft, value: ScoreDefinitionDraft[keyof ScoreDefinitionDraft]) => void
}

function explainedOption<T extends string>(value: T, label: string, example: string): LemonSelectOptionLeaf<T> {
    return {
        value,
        label,
        labelInMenu: (
            <span className="flex flex-col gap-0.5 py-1 whitespace-normal">
                <span>{label}</span>
                <span className="text-xs text-muted font-normal">{example}</span>
            </span>
        ),
    }
}

const versionPolicies = [
    explainedOption(
        'run',
        'One version per run',
        'Use v3 or v4. If both return scores, this input is unavailable. Errors and skips do not count.'
    ),
    explainedOption('exact', 'Exact version', 'Choose v3 to count only the items scored by v3.'),
    explainedOption(
        'combine',
        'Combine versions',
        'Pool scores from v3 and v4. Each item can contribute one successful score.'
    ),
]

function experimentStatistics(
    input: Pick<ScoreDefinitionDraft['inputs'][number], 'kind' | 'config'>
): LemonSelectOptionLeaf<NonNullable<ScoreDefinitionDraft['inputs'][number]['statistic']>>[] {
    const passRate = explainedOption(
        'pass_rate',
        'Pass rate',
        'Share that meets the passing rule. 8 of 10 passing gives 0.8.'
    )
    if (input.kind === 'boolean') {
        return [
            passRate,
            explainedOption('true_rate', 'True rate', 'Share scored true, even when false is the passing value.'),
        ]
    }
    const base =
        input.kind === 'numeric'
            ? explainedOption('mean', 'Mean', 'Average of the numeric scores. Scores of 2 and 4 give 3.')
            : explainedOption('category_rate', 'Category rate', 'Share with the selected category. 3 of 10 gives 0.3.')
    const config = input.kind === 'numeric' ? getNumericConfig(input.config) : getCategoricalConfig(input.config)
    return config.passing_rule ? [base, passRate] : [base]
}

export function CompositeScorerForm({
    draft,
    disabled,
    setDraftField,
    experimentId,
}: CompositeScorerFormProps): JSX.Element {
    const id = useId()
    const logic = compositeInputsLogic({
        id,
        scope: draft.scope,
        experimentId,
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
            ...(draft.scope === 'experiment' ? { scope: draft.scope } : {}),
            kind: draft.kind,
            composition: buildCompositionFromDraft(draft),
            config: buildConfigFromDraft(draft),
        })
            ? validation
            : null

    return (
        <section className="flex flex-col gap-4 @container/composite-form" aria-labelledby={`${id}-heading`}>
            <h3 id={`${id}-heading`} className="mb-0">
                {draft.scope === 'experiment' ? 'Experiment score formula' : 'Composite calculation'}
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
                            {draft.scope === 'experiment' && (
                                <>
                                    <LemonField.Pure label="Version policy">
                                        <LemonSelect
                                            value={input.version_policy ?? 'run'}
                                            disabledReason={disabled ? 'Saving scorer' : undefined}
                                            options={versionPolicies}
                                            data-attr="aio-experiment-input-version-policy"
                                            onChange={(version_policy) => updateInput(index, { version_policy })}
                                        />
                                    </LemonField.Pure>
                                    <LemonField.Pure
                                        label="Statistic"
                                        info="Only items with a successful score count toward these statistics."
                                    >
                                        <LemonSelect
                                            value={input.statistic}
                                            disabledReason={disabled ? 'Saving scorer' : undefined}
                                            options={experimentStatistics(input)}
                                            data-attr="aio-experiment-input-statistic"
                                            onChange={(statistic) => updateInput(index, { statistic })}
                                        />
                                    </LemonField.Pure>
                                    {input.statistic === 'category_rate' && (
                                        <LemonField.Pure label="Category">
                                            <LemonSelect
                                                value={input.category}
                                                disabledReason={disabled ? 'Saving scorer' : undefined}
                                                options={getCategoricalConfig(input.config).options.map(
                                                    ({ key, label }) => ({ value: key, label })
                                                )}
                                                onChange={(category) => updateInput(index, { category })}
                                            />
                                        </LemonField.Pure>
                                    )}
                                </>
                            )}
                            {(draft.scope !== 'experiment' || input.version_policy === 'exact') && (
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
                            )}
                        </div>
                        {latest.id &&
                            input.scorer_version_id !== latest.id &&
                            (draft.scope !== 'experiment' || input.version_policy === 'exact') && (
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
                                            (draft.scope === 'experiment' ||
                                                !draft.inputs.some((input) => input.definition_id === scorer.id))
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
                                            ...(draft.scope === 'experiment'
                                                ? {
                                                      statistic: experimentStatistics(scorer)[0].value,
                                                      version_policy: 'run' as const,
                                                      ...(scorer.kind === 'categorical'
                                                          ? {
                                                                category: getCategoricalConfig(scorer.config).options[0]
                                                                    ?.key,
                                                            }
                                                          : {}),
                                                  }
                                                : {}),
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
                            : draft.scope === 'experiment'
                              ? 'Averages the selected scorer statistics.'
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
                        {experimentId && draft.scope === 'experiment'
                            ? 'Preview on this experiment'
                            : 'Validate formula'}
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
                {checked?.preview && <ExperimentScoreResult score={checked.preview} />}
                {checked && !checked.preview && (
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
                                dataSource={
                                    draft.scope === 'experiment'
                                        ? [
                                              { name: 'Weighted pass rates', formula: '0.7 * score1 + 0.3 * score2' },
                                              { name: 'Both rates reach 90%', formula: 'min(score1, score2) >= 0.9' },
                                              {
                                                  name: 'Choose a category',
                                                  formula: '"good" if score1 >= 0.9 else "bad"',
                                              },
                                          ]
                                        : [
                                              { name: 'Weighted average', formula: '(2 * score1 + score2) / 3' },
                                              { name: 'Both Boolean values are true', formula: 'score1 and score2' },
                                              { name: 'True as 1, false as 0', formula: 'number(score1)' },
                                              { name: 'Check a category', formula: '"good" in score1' },
                                              { name: 'Choose a category', formula: '"good" if score1 else "bad"' },
                                          ]
                                }
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
