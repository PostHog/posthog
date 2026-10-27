import { useActions, useValues } from 'kea'

import {
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { SceneExport } from 'scenes/sceneTypes'

import { BetsPage } from '../BetsPage'
import { BetsSettingsSkeleton } from '../components/BetsSettingsSkeleton'
import { BetStepModelField } from '../components/BetStepModelField'
import { betsSettingsLogic } from '../logics/betsSettingsLogic'

export const scene: SceneExport = { component: BetsSettingsScene, logic: betsSettingsLogic }

export function BetsSettingsScene(): JSX.Element {
    const {
        overview,
        overviewLoading,
        budget,
        insight,
        insights,
        stepModels,
        minRunHours,
        goalConfirmHours,
        busy,
        message,
        failed,
        breadcrumbs,
    } = useValues(betsSettingsLogic)
    const {
        setBudget,
        setInsight,
        setStepModel,
        setMinRunHours,
        setGoalConfirmHours,
        save,
        loadSettings,
        loadInsights,
    } = useActions(betsSettingsLogic)
    const items = [
        { value: '', label: 'Choose a saved insight' },
        ...insights.map((entry) => ({
            value: entry.short_id,
            label: entry.name || entry.derived_name || entry.short_id,
        })),
    ]
    return (
        <BetsPage title="Bets settings" breadcrumbs={breadcrumbs}>
            {!overview ? (
                failed ? (
                    <div className="flex flex-col items-start gap-3 py-10" role="alert">
                        <Text variant="destructive">{message}</Text>
                        <Button
                            variant="outline"
                            loading={overviewLoading}
                            onClick={() => {
                                loadSettings()
                                loadInsights()
                            }}
                        >
                            Try again
                        </Button>
                    </div>
                ) : (
                    <BetsSettingsSkeleton />
                )
            ) : (
                <form
                    className="flex max-w-170 flex-col gap-6 pt-7"
                    onSubmit={(event) => {
                        event.preventDefault()
                        save()
                    }}
                >
                    <Field>
                        <FieldLabel htmlFor="project-budget">Project budget (USD)</FieldLabel>
                        <Input
                            id="project-budget"
                            type="number"
                            min={0}
                            step="0.01"
                            required
                            value={budget}
                            onChange={(event) => setBudget(Number(event.target.value))}
                            disabled={!overview.can_edit}
                        />
                        <FieldDescription>The total amount available to allocate across your bets.</FieldDescription>
                    </Field>
                    <Field>
                        <FieldLabel>North Star</FieldLabel>
                        <Select
                            value={insight}
                            items={items}
                            onValueChange={(value) => setInsight(value ?? '')}
                            disabled={!overview.can_edit}
                        >
                            <SelectTrigger aria-label="North Star insight">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {items.map((item) => (
                                    <SelectItem key={item.value} value={item.value}>
                                        {item.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <FieldDescription>A saved insight with one series, shown at the top of Bets.</FieldDescription>
                    </Field>
                    <fieldset className="flex flex-col gap-6 border-0 p-0 m-0">
                        <legend className="Bets__sectionTitle mb-1">Experiments</legend>
                        <div className="Bets__formRow">
                            <Field>
                                <FieldLabel htmlFor="bets-min-run-hours">Minimum experiment run (hours)</FieldLabel>
                                <Input
                                    id="bets-min-run-hours"
                                    type="number"
                                    min={0}
                                    max={1440}
                                    step="1"
                                    required
                                    value={minRunHours}
                                    onChange={(event) => setMinRunHours(Math.round(Number(event.target.value)))}
                                    disabled={!overview.can_edit}
                                />
                                <FieldDescription>
                                    Bets reads a win or a loss only after this time. A guardrail that gets worse stops
                                    the experiment at once.
                                </FieldDescription>
                            </Field>
                            <Field>
                                <FieldLabel htmlFor="bets-goal-confirm-hours">Confirm the goal for (hours)</FieldLabel>
                                <Input
                                    id="bets-goal-confirm-hours"
                                    type="number"
                                    min={0}
                                    max={1440}
                                    step="1"
                                    required
                                    value={goalConfirmHours}
                                    onChange={(event) => setGoalConfirmHours(Math.round(Number(event.target.value)))}
                                    disabled={!overview.can_edit}
                                />
                                <FieldDescription>
                                    The goal must stay at the target this long before the bet counts as reached.
                                </FieldDescription>
                            </Field>
                        </div>
                    </fieldset>
                    <fieldset className="flex flex-col gap-6 border-0 p-0 m-0">
                        <legend className="Bets__sectionTitle mb-1">Models</legend>
                        <Text size="sm" variant="muted" render={<p className="m-0" />}>
                            Choose the model and who pays for each step. Cheaper models cost less per run.
                        </Text>
                        {overview.settings.models.map((item) => (
                            <BetStepModelField
                                key={item.step}
                                step={item.step}
                                value={stepModels[item.step]}
                                options={overview.settings.model_options}
                                planAvailable={overview.settings.plan_available}
                                disabled={!overview.can_edit}
                                onChange={(patch) => setStepModel(item.step, patch)}
                            />
                        ))}
                    </fieldset>
                    {message && (
                        <Text variant={failed ? 'destructive' : 'muted'} role={failed ? 'alert' : 'status'}>
                            {message}
                        </Text>
                    )}
                    {overview.can_edit && (
                        <div>
                            <Button type="submit" variant="primary" loading={busy}>
                                Save settings
                            </Button>
                        </div>
                    )}
                </form>
            )}
        </BetsPage>
    )
}
