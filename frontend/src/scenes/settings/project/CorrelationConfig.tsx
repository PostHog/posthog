import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { IconPlus, IconSelectEvents, IconSelectProperties } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { teamLogic } from 'scenes/teamLogic'

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
            <p>Globally exclude events or properties that do not provide relevant signals for your conversions.</p>

            <LemonBanner type="info">
                Correlation analysis can automatically surface relevant signals for conversion, and help you understand
                why your users dropped off and what makes them convert.
            </LemonBanner>
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
                                <LemonButton size="small" type="secondary" icon={<IconPlus />} sideIcon={null}>
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
                        <div className="max-w-160">
                            <LemonSelectMultiple
                                mode="multiple-custom"
                                onChange={(properties: string[]) => handleChange(undefined, undefined, properties)}
                                value={funnelCorrelationConfig.excluded_event_property_names || []}
                            />
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}
