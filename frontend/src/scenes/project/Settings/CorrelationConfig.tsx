import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { IconPlus, IconSelectEvents, IconSelectProperties } from 'lib/lemon-ui/icons'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { LemonButton } from '@posthog/lemon-ui'

export function CorrelationConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, funnelCorrelationConfig } = useValues(teamLogic)

    const handleChange = (
        excludedProperties?: string[],
        excludedEvents?: string[],
        excludedEventProperties?: string[]
    ): void => {
        if (currentTeam) {
            const updatedConfig = { ...funnelCorrelationConfig }
            if (excludedProperties !== undefined) {
                updatedConfig.excluded_person_property_names = excludedProperties
            }
            if (excludedEventProperties !== undefined) {
                updatedConfig.excluded_event_property_names = excludedEventProperties
            }
            if (excludedEvents !== undefined) {
                updatedConfig.excluded_event_names = excludedEvents
            }
            if (updatedConfig && JSON.stringify(updatedConfig) !== JSON.stringify(funnelCorrelationConfig)) {
                updateCurrentTeam({ correlation_config: updatedConfig })
            }
        }
    }

    return (
        <>
            <h2 className="subtitle" id="internal-users-filtering">
                Correlation analysis exclusions{' '}
                <LemonTag type="warning" className="uppercase ml-2">
                    Beta
                </LemonTag>
            </h2>
            <p>Globally exclude events or properties that do not provide relevant signals for your conversions.</p>

            <AlertMessage type="info">
                Correlation analysis can automatically surface relevant signals for conversion, and help you understand
                why your users dropped off and what makes them convert.
            </AlertMessage>
            {currentTeam && (
                <div className="mt-4 space-y-2">
                    <div>
                        <h3 className="flex items-center gap-2">
                            <IconSelectProperties className="text-lg" />
                            Excluded person properties
                        </h3>
                        <PersonPropertySelect
                            onChange={(properties) => handleChange(properties)}
                            selectedProperties={funnelCorrelationConfig.excluded_person_property_names || []}
                            addText="Add exclusion"
                        />
                    </div>
                    <div>
                        <h3 className="flex items-center gap-2">
                            <IconSelectEvents className="text-lg" />
                            Excluded events
                        </h3>
                        <EventSelect
                            onChange={(excludedEvents) => handleChange(undefined, excludedEvents)}
                            selectedEvents={funnelCorrelationConfig.excluded_event_names || []}
                            addElement={
                                <LemonButton size="small" type="secondary" icon={<IconPlus />}>
                                    Add exclusion
                                </LemonButton>
                            }
                        />
                    </div>
                    <div>
                        <h3 className="flex items-center gap-2">
                            <IconSelectEvents className="text-lg" />
                            Excluded event properties
                        </h3>
                        <div style={{ maxWidth: '40rem' }}>
                            <LemonSelectMultiple
                                mode="multiple-custom"
                                onChange={(properties) => handleChange(undefined, undefined, properties)}
                                value={funnelCorrelationConfig.excluded_event_property_names || []}
                            />
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}
