import { ActionType } from '~/types'
import { DefinitionPopup } from 'lib/components/DefinitionPopup/DefinitionPopup'
import {
    eventToHumanName,
    genericOperatorToHumanName,
    propertyValueToHumanName,
} from 'lib/components/DefinitionPopup/utils'

export function ActionPopupInfo({ entity }: { entity: ActionType }): JSX.Element | null {
    if (!entity) {
        return null
    }
    return (
        <>
            {entity.steps &&
                entity.steps.map((step, index) => (
                    <DefinitionPopup.Section key={step.id}>
                        <DefinitionPopup.Card
                            title={`Match group ${index + 1}: ${step.event && eventToHumanName(step.event)}`}
                            value={
                                <ul>
                                    {step.selector && (
                                        <li>
                                            <span>
                                                CSS selector:<pre>{step.selector}</pre>
                                            </span>
                                        </li>
                                    )}
                                    {step.tag_name && (
                                        <li>
                                            <span>
                                                Element name:<pre>{step.tag_name}</pre>
                                            </span>
                                        </li>
                                    )}
                                    {step.text && (
                                        <li>
                                            <span>
                                                Text:<pre>{step.text}</pre>
                                            </span>
                                        </li>
                                    )}
                                    {step.href && (
                                        <li>
                                            <span>
                                                HREF attribute:<pre>{step.href}</pre>
                                            </span>
                                        </li>
                                    )}
                                    {step.url && (
                                        <li>
                                            <span>
                                                URL{' '}
                                                {step.url_matching === 'regex'
                                                    ? 'Regex:'
                                                    : step.url_matching === 'exact'
                                                    ? ':'
                                                    : 'contains:'}
                                                <pre>{step.url}</pre>
                                            </span>
                                        </li>
                                    )}
                                    {step.properties &&
                                        step.properties.map((property, propIndex) => (
                                            <li key={propIndex}>
                                                <span>
                                                    <pre>{eventToHumanName(property.key)}</pre>
                                                    {genericOperatorToHumanName(property)}
                                                    <pre>{propertyValueToHumanName(property.value)}</pre>
                                                </span>
                                            </li>
                                        ))}
                                </ul>
                            }
                        />
                        {entity.steps && index < entity.steps.length - 1 && (
                            <DefinitionPopup.HorizontalLine style={{ marginTop: 4, marginBottom: 12 }}>
                                OR
                            </DefinitionPopup.HorizontalLine>
                        )}
                    </DefinitionPopup.Section>
                ))}
        </>
    )
}
