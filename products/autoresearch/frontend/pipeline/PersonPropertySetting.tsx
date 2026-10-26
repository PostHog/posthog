import { useActions, useValues } from 'kea'

import { LemonDialog, LemonSwitch } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { PersonPropertyToggleSource, autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import type { AutoresearchRunApi } from '../generated/api.schemas'

/** The switch that decides whether scoring writes each score to the person profile, with the last cleanup's state. */
export function PersonPropertySetting({ source }: { source: PersonPropertyToggleSource }): JSX.Element | null {
    const { pipeline, savingWritePersonProperty, latestPropertyCleanupRun } = useValues(autoresearchPipelineLogic)
    const { setWritePersonProperty } = useActions(autoresearchPipelineLogic)

    const outputProperty = pipeline?.output_person_property
    if (!pipeline || !outputProperty) {
        return null
    }
    const enabled = !!pipeline.write_person_property

    const onChange = (checked: boolean): void => {
        if (checked) {
            setWritePersonProperty(true, source)
            return
        }
        LemonDialog.open({
            title: 'Stop writing scores to person profiles?',
            description: `The ${outputProperty} property will be removed from the people this model scored. Feature flags, cohorts and workflows that use it will stop matching those people. Prediction events, segments and accuracy checks keep working.`,
            primaryButton: {
                children: 'Stop writing scores',
                status: 'danger',
                onClick: () => setWritePersonProperty(false, source),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-1">
            <LemonSwitch
                bordered
                fullWidth
                label="Write scores to person profiles"
                checked={enabled}
                onChange={onChange}
                loading={savingWritePersonProperty}
                disabledReason={savingWritePersonProperty ? 'The setting is saving' : undefined}
                data-attr={`autoresearch-person-property-toggle-${source}`}
            />
            <p className="text-xs text-secondary mb-0">
                {enabled ? (
                    <span>
                        <span>Each scoring run sets </span>
                        <code>{outputProperty}</code>
                        <span>
                            {' '}
                            on the people it scores. People who were not scored yet get it over the next few scoring
                            runs.
                        </span>
                    </span>
                ) : (
                    <span>
                        <span>
                            Turn this on to target people by score in feature flags, cohorts, workflows and insights.
                            Scores go to the{' '}
                        </span>
                        <code>{outputProperty}</code>
                        <span> person property.</span>
                    </span>
                )}
            </p>
            {latestPropertyCleanupRun && !enabled && (
                <p className="text-xs text-secondary mb-0">{cleanupStatus(latestPropertyCleanupRun)}</p>
            )}
        </div>
    )
}

function cleanupStatus(run: AutoresearchRunApi): string {
    if (run.status === 'pending' || run.status === 'running') {
        return 'Removing the property from people who have it. This takes at least an hour, because a second pass removes scores that arrived late.'
    }
    if (run.status === 'failed') {
        return "Couldn't remove the property from everyone this model scored. Turn the setting on and off again to retry."
    }
    const removedFrom = run.rows_scored ?? 0
    const when = run.completed_at ? ` on ${dayjs(run.completed_at).format('MMM D, YYYY')}` : ''
    return `Removed the property from ${removedFrom.toLocaleString()} ${removedFrom === 1 ? 'person' : 'people'}${when}.`
}
